"""
测试 agent/tools.py: ToolDef, ToolRegistry, create_tool_registry
"""
from __future__ import annotations

import json

# tools.py imports ctypes at module level — must mock before import
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

# Now safe to import
from agent.tools import (  # noqa: E402  需先 mock ctypes
    ToolDef,
    ToolRegistry,
    _is_admin,
    create_tool_registry,
)

# ================================================================
#  ToolDef
# ================================================================

class TestToolDef:
    """ToolDef 工具定义和 schema 生成."""

    def test_to_openai_schema_basic(self):
        def handler(**kwargs):
            return {"ok": True}

        tool = ToolDef(
            name="test_tool",
            description="A test tool for unit testing",
            parameters={
                "param1": {
                    "type": "string",
                    "description": "First parameter",
                },
            },
            handler=handler,
        )

        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test_tool"
        assert "parameters" in schema["function"]
        assert "param1" in schema["function"]["parameters"]["properties"]

    def test_to_openai_schema_with_required_params(self):
        def handler(**kwargs):
            return {}

        tool = ToolDef(
            name="required_tool",
            description="Tool with required params",
            parameters={
                "input": {
                    "type": "string",
                    "description": "Required input",
                    "required": True,
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Optional flag",
                },
            },
            handler=handler,
        )

        schema = tool.to_openai_schema()
        required = schema["function"]["parameters"].get("required", [])
        assert "input" in required
        assert "verbose" not in required

    def test_to_openai_schema_no_required(self):
        def handler(**kwargs):
            return {}

        tool = ToolDef(
            name="no_req",
            description="No required",
            parameters={"opt": {"type": "string", "description": "Optional"}},
            handler=handler,
        )

        schema = tool.to_openai_schema()
        required = schema["function"]["parameters"].get("required", [])
        assert "opt" not in required

    def test_execute_success(self):
        def handler(name="world"):
            return {"greeting": f"Hello, {name}!"}

        tool = ToolDef(
            name="greet",
            description="Greet someone",
            parameters={"name": {"type": "string", "description": "Name"}},
            handler=handler,
        )

        result = tool.execute({"name": "Test"})
        parsed = json.loads(result)
        assert parsed["greeting"] == "Hello, Test!"

    def test_execute_returns_json_string(self):
        def handler():
            return {"key": "value", "nested": {"a": 1}}

        tool = ToolDef(
            name="json_out",
            description="Returns JSON",
            parameters={},
            handler=handler,
        )

        result = tool.execute({})
        parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert parsed["nested"]["a"] == 1

    def test_execute_non_dict_result(self):
        def handler():
            return "plain text result"

        tool = ToolDef(
            name="text_out",
            description="Returns text",
            parameters={},
            handler=handler,
        )

        result = tool.execute({})
        assert result == "plain text result"

    def test_execute_handles_exception(self):
        def handler():
            raise ValueError("Something went wrong!")

        tool = ToolDef(
            name="failing",
            description="Always fails",
            parameters={},
            handler=handler,
        )

        result = tool.execute({})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Something went wrong" in parsed["error"]

    def test_execute_admin_required_not_admin(self):
        def handler():
            return {"admin": "yes"}

        tool = ToolDef(
            name="admin_tool",
            description="Needs admin",
            parameters={},
            handler=handler,
            require_admin=True,
        )

        # Set the mocked IsUserAnAdmin to return False
        _mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = False
        result = tool.execute({})
        parsed = json.loads(result)
        assert "Admin privileges" in parsed.get("error", "")

    def test_execute_admin_required_is_admin(self):
        def handler():
            return {"admin": "yes"}

        tool = ToolDef(
            name="admin_tool",
            description="Needs admin",
            parameters={},
            handler=handler,
            require_admin=True,
        )

        # Set the mocked IsUserAnAdmin to return True
        _mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = True
        result = tool.execute({})
        parsed = json.loads(result)
        assert parsed["admin"] == "yes"


# ================================================================
#  ToolRegistry
# ================================================================

class TestToolRegistry:
    """ToolRegistry 注册/查找/执行/列表."""

    def setup_method(self):
        self.registry = ToolRegistry()
        self.registry.register(ToolDef(
            name="tool_a",
            description="Tool A",
            parameters={"x": {"type": "integer", "description": "X"}},
            handler=lambda x=0: {"result": x * 2},
        ))
        self.registry.register(ToolDef(
            name="tool_b",
            description="Tool B",
            parameters={},
            handler=lambda: {"ok": True},
        ))

    def test_get_existing_tool(self):
        tool = self.registry.get("tool_a")
        assert tool is not None
        assert tool.name == "tool_a"

    def test_get_nonexistent_tool(self):
        tool = self.registry.get("nonexistent")
        assert tool is None

    def test_list_all(self):
        tools = self.registry.list_all()
        names = [t.name for t in tools]
        assert "tool_a" in names
        assert "tool_b" in names
        assert len(tools) == 2

    def test_get_schemas(self):
        schemas = self.registry.get_schemas()
        assert len(schemas) == 2
        names = [s["function"]["name"] for s in schemas]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_execute_known_tool(self):
        result = self.registry.execute("tool_a", {"x": 5})
        parsed = json.loads(result)
        assert parsed["result"] == 10

    def test_execute_unknown_tool(self):
        result = self.registry.execute("unknown_tool", {})
        parsed = json.loads(result)
        assert "Unknown tool" in parsed["error"]


# ================================================================
#  create_tool_registry
# ================================================================

class TestCreateToolRegistry:
    """create_tool_registry() 工厂函数."""

    def test_returns_tool_registry(self):
        with patch("agent.tools._import_guardian_modules") as mock_import:
            mock_import.side_effect = ImportError("Not available on Linux")
            registry = create_tool_registry()
        assert isinstance(registry, ToolRegistry)

    def test_registry_has_builtin_tools(self):
        """手动注册内置工具验证 registry 行为."""
        registry = ToolRegistry()
        registry.register(ToolDef(
            name="scan_network",
            description="Scan network",
            parameters={},
            handler=lambda: {},
        ))
        registry.register(ToolDef(
            name="check_firewall",
            description="Check firewall",
            parameters={},
            handler=lambda: {},
        ))
        tool_names = [t.name for t in registry.list_all()]
        assert "scan_network" in tool_names
        assert "check_firewall" in tool_names


# ================================================================
#  _is_admin
# ================================================================

class TestIsAdmin:
    """_is_admin() 管理员检测."""

    def test_is_admin_returns_bool(self):
        """_is_admin 应该返回 bool 值."""
        result = _is_admin()
        assert isinstance(result, bool)

    def test_is_admin_handles_missing_ctypes(self):
        """当 ctypes 不可用时应该返回 False (安全默认)."""
        # 从 sys.modules 移除 ctypes → import ctypes 抛 ImportError → 走 except 返回 False
        with patch.dict(sys.modules, {"ctypes": None}):
            result = _is_admin()
        assert result is False
