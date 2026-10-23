"""
测试 agent/core.py: AgentCore 初始化, ReAct 循环, 工具调度, skill 匹配, MCP 集成
"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace
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

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from agent.config import AgentConfig, LLMProvider  # noqa: E402  需先 mock ctypes
from agent.core import AgentCore  # noqa: E402
from agent.tools import ToolDef, ToolRegistry  # noqa: E402

# ---- Helpers ----

def _make_minimal_config():
    return AgentConfig(
        providers=[],
        max_iterations=5,
        stream_output=False,
        mcp_servers=[],
        skill_dirs=[],
        knowledge_base_enabled=False,
        # 测试一律用内存 checkpointer，否则每个用例都会往真实的 data/ 写 SQLite
        checkpoint_backend="memory",
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


# ---- AgentCore 初始化 ----

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


# ---- _build_system_prompt ----

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


# ---- run() — ReAct Loop 基本行为 ----

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
        """run() 从 run_stream 中收集 type='text' 事件。

        这里 patch 的是 `agent.llm.chat`，而适配层 GuardianChatModel._generate
        正是转发给它 —— 所以本用例实际走的是「真实适配层 + 状态图」的完整路径，
        不是绕过它们。
        """
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=3,
            stream_output=False,
            knowledge_base_enabled=False,
            checkpoint_backend="memory",
        )
        agent = AgentCore(config, tool_registry=_make_tool_registry())

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
            result = agent.run("check security")
            assert "All systems secure" in result
            assert mock_chat.call_count == 1

    def test_run_stops_at_max_iterations(self):
        """达到 max_iterations 时停止并产生 fallback 消息。

        语义上限由 agent 节点里的 iteration 判断把关（与原 while 循环等价），
        不是靠 LangGraph 的 recursion_limit 兜底。
        """
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=2,
            stream_output=False,
            knowledge_base_enabled=False,
            checkpoint_backend="memory",
        )
        agent = AgentCore(config, tool_registry=_make_tool_registry())

        with patch.object(agent.llm, 'chat') as mock_chat:
            # 永远要求调工具 -> 只能靠迭代上限收场
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
            result = agent.run("test")
            assert isinstance(result, str)
            assert mock_chat.call_count == 2          # 恰好 max_iterations 次
            assert "Max iterations reached" in result


# ---- run_stream() ----

def _stream_events(*calls):
    """构造 LLMRouter.chat_stream 的假实现：第 N 次调用 yield 第 N 组事件。

    流式路径走的是 chat_stream 而不是 chat，所以 stream_output=True 的用例
    必须把它也 mock 掉，否则会去打真实的网络端点。
    """
    seq = list(calls)
    state = {"i": 0}

    def _impl(*args, **kwargs):
        idx = min(state["i"], len(seq) - 1)
        state["i"] += 1
        for event in seq[idx]:
            yield event

    return _impl


def _text(chunk):
    return {"type": "text", "content": chunk}


def _tool_call_events(name, args_json, call_id="c1"):
    return [{"type": "tool_call", "tool_call": {
        "id": call_id,
        "function": {"name": name, "arguments": args_json},
    }}]


class TestRunStream:
    """流式输出 ReAct 循环."""

    def test_stream_yields_text_event(self):
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=3,
            stream_output=True,
            knowledge_base_enabled=False,
            checkpoint_backend="memory",
        )
        agent = AgentCore(config, tool_registry=_make_tool_registry())

        with patch.object(agent.llm, 'chat_stream',
                          side_effect=_stream_events([_text("All "), _text("secure")])):
            events = list(agent.run_stream("status check"))
            text_events = [e for e in events if e["type"] == "text"]
            # 逐 token：两个增量事件，拼起来才是完整回复
            assert [e["content"] for e in text_events] == ["All ", "secure"]
            assert "".join(e["content"] for e in text_events) == "All secure"

    def test_stream_yields_tool_events(self):
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=5,
            stream_output=True,
            knowledge_base_enabled=False,
            checkpoint_backend="memory",
        )
        registry = _make_tool_registry()
        agent = AgentCore(config, tool_registry=registry)

        with patch.object(agent.llm, 'chat_stream',
                          side_effect=_stream_events(
                              _tool_call_events("mock_tool", '{"arg":"hello"}'),
                              [_text("Done checking")])) as mock_stream:
            events = list(agent.run_stream("check"))
            event_types = [e["type"] for e in events]
            assert event_types == ["tool_start", "tool_result", "text"]
            assert mock_stream.call_count == 2

        # 工具结果必须回喂给模型
        assert "hello" in json.dumps(events[1]["result"], ensure_ascii=False)

    def test_stream_handles_llm_error(self):
        """LLM 全部 provider 失败时产生 error 事件并停止（不是抛异常）。"""
        config = AgentConfig(
            providers=[_make_provider()],
            max_iterations=3,
            stream_output=True,
            knowledge_base_enabled=False,
            checkpoint_backend="memory",
        )
        agent = AgentCore(config)

        # 流式路径首字未出就失败 -> 回退到 invoke 路径；两条都失败才是真失败
        with patch.object(agent.llm, 'chat_stream',
                          side_effect=_stream_events(
                              [{"type": "error", "content": "API rate limit exceeded"}])), \
             patch.object(agent.llm, 'chat') as mock_chat:
            mock_chat.return_value = {
                "_ok": False,
                "_error": "API rate limit exceeded"
            }
            events = list(agent.run_stream("check"))
            error_events = [e for e in events if e["type"] == "error"]
            assert len(error_events) >= 1


# ---- MCP 工具集成 ----

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


# ---- Conversation Management ----

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


# ---- 审批闸门（经由 AgentCore 的中断循环）----

def _gated_agent(handler, **config_overrides):
    """一个带需要审批工具的 AgentCore。"""
    config = AgentConfig(
        providers=[_make_provider()],
        max_iterations=3,
        # 这些用例测的是审批闸门，不是流式，走 invoke 路径即可
        # （流式路径要 mock chat_stream，见 TestRunStream）
        stream_output=False,
        knowledge_base_enabled=False,
        checkpoint_backend="memory",
        **config_overrides,
    )
    registry = ToolRegistry()
    registry.register(ToolDef(
        name="run_command", description="run",
        parameters={"command": {"type": "string"}},
        handler=handler, requires_approval=True, risk_level="caution",
    ))
    return AgentCore(config, tool_registry=registry)


def _two_turn_llm(agent):
    """第一次要调 run_command，第二次给最终文本。"""
    responses = [
        {"_ok": True, "choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "c1", "function": {"name": "run_command",
                                      "arguments": '{"command":"ipconfig"}'}}]}}]},
        {"_ok": True, "choices": [{"message": {"role": "assistant", "content": "已执行"}}]},
    ]
    idx = [0]

    def side_effect(*args, **kwargs):
        resp = responses[min(idx[0], len(responses) - 1)]
        idx[0] += 1
        return resp

    return patch.object(agent.llm, "chat", side_effect=side_effect)


class TestApprovalThroughAgentCore:
    """core.run_stream 的中断 -> 询问 -> Command(resume) 循环。

    图本身有 test_graph.py 覆盖；这里专门验证 AgentCore 这一层的接线 ——
    它是 P3 改造里风险最高的部分（生成器 + 恢复的交互）。
    """

    def test_approved_executes_once(self):
        handler = MagicMock(return_value={"ok": True})
        agent = _gated_agent(handler)
        asked = []
        agent._ask_approval = lambda payload: (
            asked.append(payload), {"approved": True, "reason": "test"})[1]

        with _two_turn_llm(agent):
            events = list(agent.run_stream("跑一下 ipconfig"))

        assert [p["tool"] for p in asked] == ["run_command"]
        assert asked[0]["risk_level"] == "caution"
        assert handler.call_count == 1
        assert [e["type"] for e in events] == ["tool_start", "tool_result", "text"]
        assert events[-1]["content"] == "已执行"

    def test_rejected_skips_execution_and_continues(self):
        handler = MagicMock(return_value={"ok": True})
        agent = _gated_agent(handler)
        agent._ask_approval = lambda payload: {"approved": False, "reason": "test_denied"}

        with _two_turn_llm(agent) as mock_chat:
            events = list(agent.run_stream("跑一下 ipconfig"))

        assert handler.call_count == 0
        assert [e["type"] for e in events] == ["text"]     # 没有 tool_start/tool_result
        # 模型仍被调了第二次，且看到的是「被拒绝」的工具结果
        assert mock_chat.call_count == 2
        assert events[-1]["content"] == "已执行"

    def test_auto_approve_mode_never_asks(self):
        handler = MagicMock(return_value={"ok": True})
        agent = _gated_agent(handler, approval_mode="auto_approve")
        agent._ask_approval = MagicMock(side_effect=AssertionError("不该被问到"))

        with _two_turn_llm(agent):
            list(agent.run_stream("跑一下"))

        assert handler.call_count == 1

    def test_auto_reject_mode_never_asks(self):
        handler = MagicMock(return_value={"ok": True})
        agent = _gated_agent(handler, approval_mode="auto_reject")
        agent._ask_approval = MagicMock(side_effect=AssertionError("不该被问到"))

        with _two_turn_llm(agent):
            list(agent.run_stream("跑一下"))

        assert handler.call_count == 0

    def test_clear_conversation_rotates_thread(self):
        """换 thread 后旧 checkpoint 不再影响新对话。"""
        agent = _gated_agent(MagicMock(return_value={"ok": True}))
        before = agent._thread_id
        agent.clear_conversation()
        assert agent._thread_id != before
        assert agent._graph_config["configurable"]["thread_id"] == agent._thread_id

    def test_summary_skills_active_reads_last_round(self):
        agent = _gated_agent(MagicMock(return_value={"ok": True}))
        assert agent.summary()["skills_active"] is None
        assert "model" in agent.summary()


def test_query_history_tool_searches_transcript():
    """query_history 是 AgentCore 注册的工具，回查当前会话的长期副本。"""
    agent = AgentCore(_make_minimal_config())
    agent.transcripts.append_turn(
        agent.conversation_id, "t-test",
        [HumanMessage(content="防火墙状态怎么样"),
         AIMessage(content="防火墙已开启")],
    )

    parsed = json.loads(agent.tools.execute("query_history", {"query": "防火墙"}))
    assert parsed["results"]
    assert parsed["results"][0]["turn_id"] == "t-test"


def test_mcp_tool_handler_accepts_model_arguments():
    """MCP handler 必须收 **kwargs：ToolDef.execute 会把模型参数展开。"""
    agent = AgentCore(_make_minimal_config())
    fake_tool = SimpleNamespace(
        name="mcp_echo",
        description="echo",
        input_schema={"properties": {"query": {"type": "string"}}},
    )
    fake_mcp = MagicMock()
    fake_mcp.get_all_tools.return_value = [fake_tool]
    fake_mcp.total_tools = 1
    fake_mcp.connected_servers = ["fake"]
    fake_mcp.call_tool.return_value = ('{"ok": true}', "fake")

    agent.mcp = fake_mcp
    agent._merge_mcp_tools()

    parsed = json.loads(agent.tools.execute("mcp_echo", {"query": "hello"}))
    assert parsed == {"ok": True}
    fake_mcp.call_tool.assert_called_once_with("mcp_echo", {"query": "hello"})

