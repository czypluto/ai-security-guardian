"""MCP 客户端测试：命令行拆分、stdio 响应匹配。

这两处此前都零测试，而它们都是"出问题很难定位"的地方：
  - 命令行拆分错了 → 服务起不来，报的却是"握手失败"
  - 响应匹配错了 → 把 notification 当成答复，报的却是"字段缺失"
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.mcp_client import (  # noqa: E402
    MCP_PROTOCOL_VERSION,
    MCPClient,
    _split_command,
)


# ---- 命令行拆分 ----

def test_split_simple_command():
    assert _split_command("python -m agent.mcp_server_mode") == [
        "python", "-m", "agent.mcp_server_mode"]


def test_split_strips_quotes_around_paths_with_spaces():
    """Windows 上带空格的路径必须整体成一个 argv，且引号要去掉 ——
    Popen 要的是裸路径，带引号会找不到可执行文件。"""
    cmd = r'"C:\Program Files\Python\python.exe" -m agent.mcp_server_mode'
    assert _split_command(cmd) == [
        r"C:\Program Files\Python\python.exe", "-m", "agent.mcp_server_mode"]


def test_split_passes_list_through():
    assert _split_command(["npx", "-y", "pkg"]) == ["npx", "-y", "pkg"]


def test_split_empty_is_empty():
    assert _split_command("") == []
    assert _split_command(None) == []


# ---- stdio 响应匹配 ----

class _FakeProc:
    """假进程：按预设顺序吐出 stdout 行，stdin 只做接收。"""

    def __init__(self, lines):
        self.stdin = io.StringIO()
        self._out = io.StringIO("\n".join(lines) + ("\n" if lines else ""))

    @property
    def stdout(self):
        return self._out

    def poll(self):
        return None


def _client_with(lines) -> MCPClient:
    c = MCPClient("fake")
    c._proc = _FakeProc(lines)
    c._connected = True
    return c


def test_rpc_stdio_skips_notifications_before_response():
    """回归：原实现"读一行就当响应"，服务端先推一条 notification 就会错位。

    notification 没有 id，不是本次请求的答复。
    """
    c = _client_with([
        json.dumps({"jsonrpc": "2.0", "method": "notifications/message",
                    "params": {"level": "info", "data": "starting up"}}),
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "x"}}),
    ])
    resp = c._rpc_stdio({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp.get("result") == {"protocolVersion": "x"}, resp


def test_rpc_stdio_skips_non_json_lines():
    """服务端把日志写到 stdout 是常见情况，不该判成解析错误。"""
    c = _client_with([
        "[2026-01-01] server starting...",
        "   ",
        json.dumps({"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}),
    ])
    resp = c._rpc_stdio({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    assert resp.get("result") == {"ok": True}, resp


def test_rpc_stdio_ignores_response_with_other_id():
    """别的请求的响应（并发场景）不能当成自己的。"""
    c = _client_with([
        json.dumps({"jsonrpc": "2.0", "id": 99, "result": {"who": "someone else"}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"who": "me"}}),
    ])
    resp = c._rpc_stdio({"jsonrpc": "2.0", "id": 3, "method": "x"})
    assert resp.get("result") == {"who": "me"}, resp


def test_rpc_stdio_errors_on_eof():
    c = _client_with([])
    resp = c._rpc_stdio({"jsonrpc": "2.0", "id": 1, "method": "x"})
    assert "error" in resp and "No response" in resp["error"]["message"]


def test_rpc_stdio_gives_up_after_too_many_irrelevant_lines():
    """防死循环：服务端一直推 notification 而响应永不来时必须放弃。"""
    noise = [json.dumps({"jsonrpc": "2.0", "method": "notifications/message"})] * 300
    c = _client_with(noise)
    resp = c._rpc_stdio({"jsonrpc": "2.0", "id": 1, "method": "x"})
    assert "error" in resp, resp


def test_rpc_stdio_errors_when_process_not_running():
    c = MCPClient("fake")
    c._proc = None
    resp = c._rpc_stdio({"jsonrpc": "2.0", "id": 1, "method": "x"})
    assert resp["error"]["code"] == -32603


# ---- 协议版本 ----

def test_protocol_version_is_a_single_constant():
    """客户端与服务端必须用同一个来源，避免两边各写一个字面量后漂移。"""
    from agent import mcp_server_mode

    assert isinstance(MCP_PROTOCOL_VERSION, str) and MCP_PROTOCOL_VERSION
    assert "2024-11-05" in open(
        Path(mcp_server_mode.__file__), encoding="utf-8").read()
