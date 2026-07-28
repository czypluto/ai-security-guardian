"""
Guardian MCP Server — Expose built-in tools as an MCP-compatible server.

Runs over stdio (one JSON-RPC line per message). External MCP clients
(including Claude Code!) can connect and use guardian's security tools.

Usage:
  python -m agent.mcp_server_mode
  # or from Claude Code config:
  # { "mcpServers": { "guardian": {
  #     "command": "python", "args": ["-m", "agent.mcp_server_mode"]
  # }}}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure we can import from agent package
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "pc_agent"))

from .tools import create_tool_registry


class GuardianMCPServer:
    """JSON-RPC 2.0 MCP server over stdio."""

    def __init__(self):
        self.tools = create_tool_registry()
        self._initialized = False

    def run(self):
        """Main loop: read JSON-RPC requests from stdin, write responses to stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                self._write_error(None, -32700, "Parse error")
                continue

            response = self._handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()

    def _handle(self, request: dict) -> dict | None:
        """Dispatch JSON-RPC method."""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        # Notifications (no id) — no response
        if req_id is None:
            return None

        if method == "initialize":
            return self._respond(req_id, self._initialize(params))
        elif method == "initialized":
            return None  # Notification, no response
        elif method == "tools/list":
            return self._respond(req_id, self._list_tools())
        elif method == "tools/call":
            return self._respond(req_id, self._call_tool(params))
        elif method == "resources/list":
            return self._respond(req_id, self._list_resources())
        elif method == "resources/read":
            return self._respond(req_id, self._read_resource(params))
        else:
            return self._respond_error(req_id, -32601, f"Method not found: {method}")

    def _respond(self, req_id, result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _respond_error(self, req_id, code, message):
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}

    def _initialize(self, params: dict) -> dict:
        self._initialized = True
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
            },
            "serverInfo": {
                "name": "ai-security-guardian",
                "version": "2.0.0",
            },
        }

    def _list_tools(self) -> dict:
        tools = []
        for t in self.tools.list_all():
            tools.append({
                "name": t.name,
                "description": t.description,
                "inputSchema": {
                    "type": "object",
                    "properties": t.parameters,
                    "required": [k for k, v in t.parameters.items()
                                 if v.get("required")],
                },
            })
        return {"tools": tools}

    def _call_tool(self, params: dict) -> dict:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result_text = self.tools.execute(tool_name, arguments)
        return {
            "content": [{"type": "text", "text": result_text}],
        }

    def _list_resources(self) -> dict:
        return {"resources": [
            {"uri": "guardian://state", "name": "System State",
             "description": "Current security state snapshot"},
            {"uri": "guardian://tools", "name": "Available Tools",
             "description": "List of available security tools"},
        ]}

    def _read_resource(self, params: dict) -> dict:
        uri = params.get("uri", "")
        if uri == "guardian://state":
            content = json.dumps({"status": "ok", "tools": len(self.tools.list_all())})
        elif uri == "guardian://tools":
            content = json.dumps(
                {"tools": [t.name for t in self.tools.list_all()]})
        else:
            content = json.dumps({"error": f"Unknown resource: {uri}"})
        return {"contents": [{"uri": uri, "text": content}]}


if __name__ == "__main__":
    server = GuardianMCPServer()
    server.run()
