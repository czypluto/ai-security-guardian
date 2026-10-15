"""
MCP Client — agent/mcp_client.py

JSON-RPC 2.0 client for Model Context Protocol (MCP).
Like Claude Code, this connects to external MCP servers to discover and call
their tools. Add servers to config.yaml → mcp_servers — agent auto-discovers.

Classes:
  MCPTool       — Wraps a tool discovered from an MCP server
  MCPClient     — JSON-RPC 2.0 client for ONE MCP server (stdio or HTTP)
  MCPManager    — Manages multiple MCP server connections

Protocol: MCP spec（版本见 MCP_PROTOCOL_VERSION，服务端会做版本协商）
  initialize   → handshake, get capabilities
  tools/list   → discover available tools
  tools/call   → execute a tool, return result
  resources/*  → (future) read resources

Transport modes:
  stdio: spawn subprocess, write JSON-RPC lines to stdin, read from stdout
  HTTP:  POST JSON-RPC to endpoint URL

Security: MCP servers run as subprocesses with CREATE_NO_WINDOW.
They CAN execute arbitrary code — only connect to trusted servers.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import weakref
import threading
import urllib.error
import urllib.request
import uuid
from typing import Optional

logger = logging.getLogger("Guardian.MCP")


class MCPTool:
    """A tool discovered from an MCP server."""
    def __init__(self, name: str, description: str, input_schema: dict,
                 server_name: str):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.server_name = server_name  # Which MCP server this came from

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


# 与 MCP 服务端协商的协议版本。服务端会按自己支持的版本回应（版本协商），
# 所以跟进新版本一般是安全的；若某个第三方 server 握手失败，先看这里是不是落后了。
MCP_PROTOCOL_VERSION = "2024-11-05"

# 读 stdio 响应时最多容忍多少条无关消息（notification / 非 JSON 行）后放弃。
# 防的是「服务端一直推 notification 而请求的响应永不来」这种死循环。
_STDIO_SKIP_LIMIT = 100


def _split_command(command) -> list:
    """把配置里的命令行拆成 argv。

    配置给的是**整条命令**（如 `python -m agent.mcp_server_mode`）。
    原实现直接把它交给 `shell=True` 让系统去拆 —— 代价实测如下：

    - **孤儿进程**：`Popen` 拿到的是 shell 进程，`terminate()` 杀掉 shell 之后
      真正的服务进程会留下来。实测（Windows）`Popen(cmd, shell=True)` 起了 2 个子进程，
      terminate() 后**两个都还活着**。每连一次 MCP 就漏一组进程。
    - Windows 上走 `cmd.exe`，带空格的路径引用规则与 POSIX 不同。
    - 每个 MCP 服务多一个无用的 shell 进程。

    代价是不能用管道、通配符、`%VAR%` 展开 —— MCP 命令本就不该依赖这些。
    """
    import shlex
    if not command:                      # None / 空串 / 空列表都当作"没给命令"
        return []
    if isinstance(command, (list, tuple)):
        return [str(x) for x in command]
    parts = shlex.split(str(command), posix=(os.name != "nt"))
    # posix=False 时 shlex 把成对引号原样留下，而 Popen 要的是裸路径
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]


class MCPClient:
    """JSON-RPC 2.0 client for one MCP server."""

    def __init__(self, name: str, transport: str = "stdio",
                 command: str = None, url: str = None, env: dict = None):
        self.name = name
        self.transport = transport
        self.command = command
        self.url = url
        self.env = env or {}
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._tools: dict[str, MCPTool] = {}
        self._connected = False

    # ---- Connect / Disconnect ----

    def connect(self) -> bool:
        """Connect and handshake. Returns True on success."""
        try:
            if self.transport == "stdio":
                return self._connect_stdio()
            elif self.transport == "http":
                return self._connect_http()
            else:
                logger.error(f"MCP[{self.name}]: unknown transport {self.transport}")
                return False
        except Exception as e:
            logger.error(f"MCP[{self.name}]: connect failed: {e}")
            return False

    def _connect_stdio(self) -> bool:
        if not self.command:
            logger.error(f"MCP[{self.name}]: no command for stdio transport")
            return False

        argv = _split_command(self.command)
        if not argv:
            logger.error(f"MCP[{self.name}]: command 解析后为空：{self.command!r}")
            return False

        import os
        merged_env = os.environ.copy()
        merged_env.update(self.env)

        self._proc = subprocess.Popen(
            argv,
            # 不用 shell=True：见 _split_command 的说明（孤儿进程 / cmd.exe 引用规则）
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged_env,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return self._handshake()

    def _connect_http(self) -> bool:
        if not self.url:
            logger.error(f"MCP[{self.name}]: no URL for HTTP transport")
            return False
        return self._handshake()

    def _handshake(self) -> bool:
        """MCP initialize handshake."""
        resp = self._rpc_call("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ai-security-guardian", "version": "2.0.0"},
        })
        if resp.get("error"):
            logger.error(f"MCP[{self.name}]: initialize failed: {resp['error']}")
            return False

        capabilities = resp.get("result", {}).get("capabilities", {})
        server_info = resp.get("result", {}).get("serverInfo", {})
        self._connected = True
        logger.info(f"MCP[{self.name}]: connected ({server_info.get('name', 'unknown')} "
                    f"v{server_info.get('version', '?')}, "
                    f"tools={bool(capabilities.get('tools'))}, "
                    f"resources={bool(capabilities.get('resources'))})")

        # Discover tools
        self._discover_tools()
        return True

    def disconnect(self):
        self._connected = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._tools.clear()

    # ---- Tool Discovery ----

    def _discover_tools(self):
        resp = self._rpc_call("tools/list", {})
        if resp.get("error"):
            logger.warning(f"MCP[{self.name}]: tools/list failed: {resp['error']}")
            return

        tools = resp.get("result", {}).get("tools", [])
        for t in tools:
            name = t.get("name", "unknown")
            self._tools[name] = MCPTool(
                name=name,
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=self.name,
            )
        logger.info(f"MCP[{self.name}]: discovered {len(self._tools)} tools: "
                    f"{list(self._tools.keys())}")

    @property
    def tools(self) -> dict[str, MCPTool]:
        return self._tools

    # ---- Tool Execution ----

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool on this MCP server. Returns JSON string."""
        if not self._connected:
            return json.dumps({"error": f"MCP[{self.name}] not connected"})

        resp = self._rpc_call("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if resp.get("error"):
            return json.dumps({"error": resp["error"]})

        content = resp.get("result", {}).get("content", [])
        # MCP returns content as list of {type, text} objects
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)
        return "\n".join(texts) if texts else json.dumps(resp["result"])

    # ---- JSON-RPC 2.0 Transport ----

    def _rpc_call(self, method: str, params: dict) -> dict:
        """Send JSON-RPC 2.0 request and return parsed response."""
        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        if self.transport == "stdio":
            return self._rpc_stdio(request)
        elif self.transport == "http":
            return self._rpc_http(request)
        else:
            return {"error": {"code": -32603, "message": f"Unknown transport: {self.transport}"}}

    def _rpc_stdio(self, request: dict) -> dict:
        """Send JSON-RPC over stdio, read until the **matching** response arrives.

        原实现是「写一行、读一行，就当那行是响应」。但 MCP 服务端会**主动推
        notification**（`notifications/message`、进度、`tools/list_changed` 等），
        它们没有 `id`、也不是本次请求的答复。只要有一条排在响应之前，
        原实现就会把它当成 initialize / tools/list 的返回值 —— 握手失败，
        而且报出来的是"字段缺失"之类的表象，很难定位到根因。

        这里按 `id` 匹配，并跳过 notification 与非 JSON 行
        （服务端把日志写到 stdout 是常见情况，不该判成解析错误）。

        注意：**stdio 这条路由没有读超时** —— 服务端卡住不返回时 `readline()`
        会一直阻塞。要治它得加读线程或非阻塞 IO，那是另一件事，此处没做。
        """
        if not self._proc or self._proc.poll() is not None:
            return {"error": {"code": -32603, "message": "MCP process not running"}}

        want = request.get("id")
        try:
            self._proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            self._connected = False
            return {"error": {"code": -32603, "message": f"Pipe broken: {e}"}}

        skipped = 0
        while True:
            try:
                response_line = self._proc.stdout.readline()
            except (BrokenPipeError, OSError) as e:
                self._connected = False
                return {"error": {"code": -32603, "message": f"Pipe broken: {e}"}}

            if not response_line:
                return {"error": {"code": -32603, "message": "No response from MCP server"}}

            try:
                msg = json.loads(response_line)
            except json.JSONDecodeError:
                skipped += 1
                if skipped > _STDIO_SKIP_LIMIT:
                    return {"error": {"code": -32700,
                                      "message": f"连续 {skipped} 行非 JSON，放弃"}}
                continue

            if isinstance(msg, dict) and msg.get("id") == want:
                return msg

            skipped += 1
            got = msg.get("id") if isinstance(msg, dict) else None
            logger.debug("MCP[%s]: 跳过无关消息 (id=%r, 期待 %r)", self.name, got, want)
            if skipped > _STDIO_SKIP_LIMIT:
                return {"error": {"code": -32603,
                                  "message": f"跳过 {skipped} 条后仍未等到 id={want!r} 的响应"}}

    def _rpc_http(self, request: dict) -> dict:
        """Send JSON-RPC over HTTP POST."""
        try:
            data = json.dumps(request, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            return {"error": {"code": -32603, "message": f"HTTP error: {e}"}}
        except Exception as e:
            return {"error": {"code": -32603, "message": str(e)}}


# ---- Multi-Server Manager ----

# 进程退出时收尾 MCP 子进程。
#
# 为什么必须有：实测（Windows）**父进程正常退出带不走子进程** ——
# 起一个 Popen 子进程、父进程正常结束，2 秒后子进程仍然存活。
# 而 `disconnect_all()` 在此之前**没有任何调用点**，也没有 atexit / shutdown 钩子，
# 于是每跑一次应用就漏一组 MCP 服务，跨重启累积。
# （顺带一提：这条是在"去删看起来是死代码的 disconnect_all"时才发现的 ——
#   它不是死代码，是漏了调用。）
#
# 为什么用 WeakSet 而不是逐个 atexit.register(self.mcp.disconnect_all)：
# `AgentCore` 会被反复创建（光测试里就 20+ 次），注册绑定方法会让每个实例
# 被强引用到进程结束 —— 那是另一种泄漏。WeakSet 不持有对象，
# 且全局只注册一个回调。
_live_managers: "weakref.WeakSet[MCPManager]" = weakref.WeakSet()
_cleanup_registered = False


def _disconnect_all_live() -> None:
    for mgr in list(_live_managers):
        try:
            mgr.disconnect_all()
        except Exception as e:  # noqa: BLE001
            logger.warning("退出时断开 MCP 服务失败: %s", e)


class MCPManager:
    """Manage multiple MCP server connections."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        global _cleanup_registered
        _live_managers.add(self)
        if not _cleanup_registered:
            atexit.register(_disconnect_all_live)
            _cleanup_registered = True

    def add_server(self, name: str, config: dict) -> MCPClient:
        """Add and connect an MCP server from config."""
        client = MCPClient(
            name=name,
            transport=config.get("transport", "stdio"),
            command=config.get("command"),
            url=config.get("url"),
            env=config.get("env"),
        )
        if client.connect():
            self._clients[name] = client
        else:
            logger.warning(f"MCP server '{name}' failed to connect — skipping")
        return client

    def add_servers_from_config(self, servers: list[dict]):
        """Add all servers from config.mcp_servers list."""
        for entry in servers:
            name = entry.get("name", str(uuid.uuid4().hex[:6]))
            self.add_server(name, entry)

    def get_all_tools(self) -> list[MCPTool]:
        """Get all tools from all connected MCP servers."""
        all_tools = []
        for client in self._clients.values():
            all_tools.extend(client.tools.values())
        return all_tools

    def call_tool(self, tool_name: str, arguments: dict) -> tuple[str, str]:
        """Find and execute tool across all servers. Returns (result_json, server_name)."""
        for client in self._clients.values():
            if tool_name in client.tools:
                return client.call_tool(tool_name, arguments), client.name
        return json.dumps({"error": f"Tool '{tool_name}' not found on any MCP server"}), ""

    def disconnect_all(self):
        for client in self._clients.values():
            client.disconnect()
        self._clients.clear()

    @property
    def connected_servers(self) -> list[str]:
        return list(self._clients.keys())

    @property
    def total_tools(self) -> int:
        return sum(len(c.tools) for c in self._clients.values())


