"""
MCP Client — agent/mcp_client.py

JSON-RPC 2.0 client for Model Context Protocol (MCP).
Like Claude Code, this connects to external MCP servers to discover and call
their tools. Add servers to config.yaml → mcp_servers — agent auto-discovers.

Classes:
  MCPTool       — Wraps a tool discovered from an MCP server
  MCPClient     — JSON-RPC 2.0 client for ONE MCP server (stdio or HTTP)
  MCPManager    — Manages multiple MCP server connections

Protocol: MCP spec 2024-11-05
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

import json
import logging
import subprocess
import threading
import time
import uuid
from typing import Optional

import urllib.request
import urllib.error

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

    # ================================================================
    #  Connect / Disconnect
    # ================================================================

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

        import os
        merged_env = os.environ.copy()
        merged_env.update(self.env)

        self._proc = subprocess.Popen(
            self.command,
            shell=True,
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
            "protocolVersion": "2024-11-05",
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

    # ================================================================
    #  Tool Discovery
    # ================================================================

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

    # ================================================================
    #  Tool Execution
    # ================================================================

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

    # ================================================================
    #  JSON-RPC 2.0 Transport
    # ================================================================

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
        """Send JSON-RPC over stdio, read one-line response."""
        if not self._proc or self._proc.poll() is not None:
            return {"error": {"code": -32603, "message": "MCP process not running"}}

        try:
            line = json.dumps(request, ensure_ascii=False) + "\n"
            self._proc.stdin.write(line)
            self._proc.stdin.flush()

            response_line = self._proc.stdout.readline()
            if not response_line:
                return {"error": {"code": -32603, "message": "No response from MCP server"}}

            return json.loads(response_line)
        except (BrokenPipeError, OSError) as e:
            self._connected = False
            return {"error": {"code": -32603, "message": f"Pipe broken: {e}"}}
        except json.JSONDecodeError as e:
            return {"error": {"code": -32700, "message": f"Parse error: {e}"}}

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


# ================================================================
#  Multi-Server Manager
# ================================================================

class MCPManager:
    """Manage multiple MCP server connections."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}

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
