"""测试 agent/graph_tools.py: ToolDef -> BaseTool 适配与审批元数据。

约定与 test_tools.py 一致：agent.tools 在模块层 import ctypes，必须先 mock。
"""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

_mock_ctypes = MagicMock()
_mock_ctypes.windll = MagicMock()
_mock_ctypes.windll.shell32 = MagicMock()
_mock_ctypes.windll.shell32.IsUserAnAdmin = MagicMock(return_value=False)
_mock_ctypes.windll.kernel32 = MagicMock()
_mock_ctypes.wintypes = MagicMock()
_mock_ctypes.Structure = type
sys.modules["ctypes"] = _mock_ctypes

from agent.graph_tools import (  # noqa: E402  需先 mock ctypes
    build_object_schema,
    to_langchain_tool,
    to_langchain_tools,
)
from agent.tools import (  # noqa: E402
    APPROVAL_REQUIRED_TOOLS,
    ToolDef,
    ToolRegistry,
    create_tool_registry,
)


def _registry_with_builtins():
    """走 fallback 分支拿内置工具，避免依赖 Windows 专属模块。"""
    with patch("agent.tools._import_guardian_modules") as mock_import:
        mock_import.side_effect = ImportError("not available")
        return create_tool_registry()


# ---- schema ----

class TestBuildObjectSchema:
    def test_required_is_derived_per_parameter(self):
        """required 以每个参数自己的 required 键为准，与 to_openai_schema 同口径。"""
        schema = build_object_schema({
            "a": {"type": "string", "required": True},
            "b": {"type": "integer"},
        })
        assert schema["type"] == "object"
        assert schema["required"] == ["a"]

    def test_empty_parameters(self):
        assert build_object_schema({})["properties"] == {}
        assert build_object_schema(None)["required"] == []


# ---- 审批元数据 ----

class TestApprovalMetadata:
    def test_three_tools_require_approval(self):
        registry = _registry_with_builtins()
        flagged = {t.name for t in registry.list_all() if t.requires_approval}
        assert flagged == set(APPROVAL_REQUIRED_TOOLS)

    def test_approval_constant_matches_flags(self):
        """常量是派生视图，必须与 ToolDef 上的标志一致（防止两处真相漂移）。"""
        registry = _registry_with_builtins()
        by_name = {t.name: t for t in registry.list_all()}
        for name in APPROVAL_REQUIRED_TOOLS:
            assert name in by_name, f"{name} 不在注册表里"
            assert by_name[name].requires_approval is True

    def test_scan_network_is_not_gated(self):
        by_name = {t.name: t for t in _registry_with_builtins().list_all()}
        assert by_name["scan_network"].requires_approval is False

    def test_risk_levels_are_set(self):
        by_name = {t.name: t for t in _registry_with_builtins().list_all()}
        assert by_name["run_command"].risk_level == "caution"
        assert by_name["install_skill"].risk_level == "sensitive"
        assert by_name["scan_network"].risk_level == "safe"

    def test_openai_schema_does_not_leak_metadata(self):
        """审批策略绝不能出现在给模型看的 function schema 里。"""
        by_name = {t.name: t for t in _registry_with_builtins().list_all()}
        schema = by_name["run_command"].to_openai_schema()
        assert set(schema) == {"type", "function"}
        assert set(schema["function"]) == {"name", "description", "parameters"}
        assert "requires_approval" not in json.dumps(schema)
        assert "risk_level" not in json.dumps(schema)


# ---- BaseTool 适配 ----

class TestGuardianTool:
    def test_carries_metadata(self):
        registry = ToolRegistry()
        registry.register(ToolDef(
            name="run_command", description="d", parameters={"command": {"type": "string"}},
            handler=lambda command: {"ok": command},
            requires_approval=True, risk_level="caution",
        ))
        tool = to_langchain_tool(registry.get("run_command"), registry)
        assert tool.requires_approval is True
        assert tool.risk_level == "caution"
        assert tool.args_schema["type"] == "object"

    def test_run_delegates_to_registry(self):
        """执行仍走 registry.execute —— require_admin 校验与 JSON 契约一条不少。"""
        registry = ToolRegistry()
        registry.register(ToolDef(
            name="echo", description="d",
            parameters={"command": {"type": "string"}},
            handler=lambda command: {"echo": command},
        ))
        tool = to_langchain_tool(registry.get("echo"), registry)
        assert json.loads(tool.invoke({"command": "ipconfig"})) == {"echo": "ipconfig"}

    def test_to_langchain_tools_covers_registry(self):
        registry = _registry_with_builtins()
        tools = to_langchain_tools(registry)
        assert len(tools) == len(registry.list_all())
        assert all(isinstance(t.name, str) for t in tools)
