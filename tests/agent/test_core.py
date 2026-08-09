"""
测试 agent/core.py: AgentCore 初始化, ReAct 循环, 工具调度, skill 匹配, MCP 集成
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# Patch ctypes before importing agent modules
_mock_ctypes = MagicMock()
_mock_ctypes.windll = MagicMock()
_mock_ctypes.windll.kernel32 = MagicMock()
_mock_ctypes.windll.shell32 = MagicMock()
_mock_ctypes.windll.shell32.IsUserAnAdmin = MagicMock(return_value=False)
_mock_ctypes.wintypes = MagicMock()
_mock_ctypes.Structure = type
sys.modules["ctypes"] = _mock_ctypes

import pytest
from agent.config import AgentConfig, LLMProvider
from agent.core import AgentCore
from agent.tools import ToolRegistry, ToolDef


# ================================================================
#  Helpers
# ================================================================

def _make_minimal_config():
    return AgentConfig(
        providers=[],
        max_iterations=5,
        stream_output=False,
        mcp_servers=[],
        skill_dirs=[],
        knowledge_base_enabled=False,
    )


def _make_provider():
    return LLMProvider(
        name="test-provider",
        api_key="sk-test",
        base_url="https://test.api.com/v1",
        model="test-model",
    )


def _make_tool_registry():
    registry = ToolRegistry()
    registry.register(ToolDef(
        name="mock_tool",
        description="A mock tool",
        parameters={"arg": {"type": "string", "description": "Argument"}},
        handler=lambda arg="default": {"result": arg},
    ))
    return registry


# ================================================================
#  AgentCore 初始化
# ================================================================

class TestAgentCoreInit:
    """AgentCore.__init__() 和各组件集成."""

    def test_basic_construction(self):
        config = _make_minimal_config()
        agent = AgentCore(config)
        assert agent.config is config
        assert agent._kb_enabled is False

    def test_construction_with_tool_registry(self):
        config = _make_minimal_config()
        registry = _make_tool_registry()
        agent = AgentCore(config, tool_registry=registry)
        assert agent.tools is registry

    def test_construction_with_providers(self):
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=5,
            stream_output=False,
            knowledge_base_enabled=False,
        )
        agent = AgentCore(config)
        assert agent.llm is not None

    def test_knowledge_base_enabled(self):
        mock_kb = MagicMock()
        config = AgentConfig(
            providers=[],
            knowledge_base_enabled=True,
            knowledge_base_top_k=5,
        )
        agent = AgentCore(config, knowledge_base=mock_kb)
        assert agent._kb_enabled is True
        assert agent._kb_top_k == 5

    def test_knowledge_base_disabled_when_none(self):
        config = AgentConfig(
            providers=[],
            knowledge_base_enabled=True,
        )
        agent = AgentCore(config, knowledge_base=None)
        assert agent._kb_enabled is False

    def test_summary_method(self):
        config = _make_minimal_config()
        agent = AgentCore(config)
        s = agent.summary()
        assert "model" in s
        assert "builtin_tools" in s
        assert "mcp_tools" in s

    def test_active_model_property(self):
        config = AgentConfig(providers=[_make_provider()])
        agent = AgentCore(config)
        active = agent.active_model
        assert "test-provider" in active


# ================================================================
#  _build_system_prompt
# ================================================================

class TestSystemPrompt:
    """系统提示词构建."""

    def test_basic_prompt_has_guardian_persona(self):
        config = _make_minimal_config()
        agent = AgentCore(config)
        prompt = agent._build_system_prompt()
        assert "安小盾" in prompt

    def test_prompt_contains_tool_descriptions(self):
        config = _make_minimal_config()
        agent = AgentCore(config)
        prompt = agent._build_system_prompt()
        assert "scan_network" in prompt


# ================================================================
#  run() — ReAct Loop 基本行为
# ================================================================

class TestRunBasic:
    """run() 基本行为."""

    def test_run_returns_text_when_no_llm(self):
        """没有 LLM provider 时返回空字符串 (空 events)."""
        config = _make_minimal_config()  # No providers
        agent = AgentCore(config)
        result = agent.run("Test query")
        # Without LLM, no text events are yielded
        assert isinstance(result, str)

    def test_run_collects_text_events(self):
        """run() 从 run_stream 中收集 type='text' 事件."""
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=3,
            stream_output=False,
            knowledge_base_enabled=False,
        )
        agent = AgentCore(config, tool_registry=_make_tool_registry())

        # Mock LLM to return a proper dict response that produces text
        with patch.object(agent.llm, 'chat') as mock_chat:
            mock_chat.return_value = {
                "_ok": True,
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "All systems secure."
                    }
                }]
            }
            with patch.object(agent.llm, 'has_tool_calls', return_value=False), \
                 patch.object(agent.llm, 'extract_reply', return_value="All systems secure."):
                result = agent.run("check security")
                assert "All systems secure" in result

    def test_run_stops_at_max_iterations(self):
        """达到 max_iterations 时停止并产生 fallback 消息."""
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=2,
            stream_output=False,
            knowledge_base_enabled=False,
        )
        agent = AgentCore(config, tool_registry=_make_tool_registry())

        with patch.object(agent.llm, 'chat') as mock_chat:
            # Always returns a tool call so the loop doesn't exit on text
            mock_chat.return_value = {
                "_ok": True,
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "tool_calls": [{
                            "id": "call_1",
                            "function": {"name": "mock_tool", "arguments": '{"arg":"test"}'}
                        }]
                    }
                }]
            }
            with patch.object(agent.llm, 'has_tool_calls', return_value=True), \
                 patch.object(agent.llm, 'extract_tool_calls', return_value=[{
                     "function": {"name": "mock_tool", "arguments": '{"arg":"test"}'}
                 }]):
                result = agent.run("test")
                assert isinstance(result, str)


# ================================================================
#  run_stream()
# ================================================================

class TestRunStream:
    """流式输出 ReAct 循环."""

    def test_stream_yields_text_event(self):
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=3,
            stream_output=True,
            knowledge_base_enabled=False,
        )
        agent = AgentCore(config, tool_registry=_make_tool_registry())

        with patch.object(agent.llm, 'chat') as mock_chat:
            mock_chat.return_value = {
                "_ok": True,
                "choices": [{
                    "message": {"role": "assistant", "content": "All secure"}
                }]
            }
            with patch.object(agent.llm, 'has_tool_calls', return_value=False), \
                 patch.object(agent.llm, 'extract_reply', return_value="All secure"):
                events = list(agent.run_stream("status check"))
                text_events = [e for e in events if e["type"] == "text"]
                assert len(text_events) >= 1
                assert "All secure" in text_events[0]["content"]

    def test_stream_yields_tool_events(self):
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=5,
            stream_output=True,
            knowledge_base_enabled=False,
        )
        registry = _make_tool_registry()
        agent = AgentCore(config, tool_registry=registry)

        responses = [
            {  # First: tool call
                "_ok": True,
                "choices": [{"message": {"role": "assistant",
                    "tool_calls": [{"id": "c1", "function": {
                        "name": "mock_tool", "arguments": '{"arg":"hello"}'
                    }}]}
                }]
            },
            {  # Second: final text
                "_ok": True,
                "choices": [{"message": {"role": "assistant",
                    "content": "Done checking"}}]
            },
        ]
        call_idx = [0]
        def chat_side_effect(*args, **kwargs):
            resp = responses[call_idx[0]]
            call_idx[0] += 1
            return resp

        tool_call_results = [True, False]

        with patch.object(agent.llm, 'chat', side_effect=chat_side_effect), \
             patch.object(agent.llm, 'has_tool_calls', side_effect=tool_call_results), \
             patch.object(agent.llm, 'extract_tool_calls', return_value=[{
                 "function": {"name": "mock_tool", "arguments": '{"arg":"hello"}'}
             }]), \
             patch.object(agent.llm, 'extract_reply', return_value="Done checking"):
            events = list(agent.run_stream("check"))
            event_types = [e["type"] for e in events]
            assert "tool_start" in event_types
            assert "tool_result" in event_types
            assert "text" in event_types

    def test_stream_handles_llm_error(self):
        """LLM 返回错误时产生 error 事件并停止."""
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=3,
            stream_output=True,
            knowledge_base_enabled=False,
        )
        agent = AgentCore(config)

        with patch.object(agent.llm, 'chat') as mock_chat:
            mock_chat.return_value = {
                "_ok": False,
                "_error": "API rate limit exceeded"
            }
            events = list(agent.run_stream("check"))
            error_events = [e for e in events if e["type"] == "error"]
            assert len(error_events) >= 1


# ================================================================
#  MCP 工具集成
# ================================================================

class TestMCPIntegration:
    """MCP 工具合并."""

    def test_mcp_tools_merged(self):
        config = _make_minimal_config()
        agent = AgentCore(config)

        # Create mock MCP tools that match what get_all_tools returns
        mock_mcp = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "mcp_external"
        mock_tool.description = "External MCP tool"
        mock_tool.input_schema = {"properties": {}}
        mock_mcp.get_all_tools.return_value = [mock_tool]
        mock_mcp.total_tools = 1
        mock_mcp.connected_servers = 1
        agent.mcp = mock_mcp

        agent._merge_mcp_tools()

        # Tool should be in registry
        tool = agent.tools.get("mcp_external")
        assert tool is not None


# ================================================================
#  Conversation Management
# ================================================================

class TestConversationManagement:
    """对话历史管理."""

    def test_clear_conversation(self):
        config = _make_minimal_config()
        agent = AgentCore(config)
        agent._conversation_messages = [{"role": "user", "content": "hello"}]
        agent.clear_conversation()
        assert agent._conversation_messages == []

    def test_save_conversation_no_messages(self):
        config = _make_minimal_config()
        agent = AgentCore(config)
        result = agent.save_conversation()
        assert result is None

    def test_save_conversation_kb_disabled(self):
        config = _make_minimal_config()
        agent = AgentCore(config)
        agent._conversation_messages = [{"role": "user", "content": "test"}]
        assert agent._kb_enabled is False
        result = agent.save_conversation()
        assert result is None
