"""测试 agent/graph.py: 状态图的编排、审批闸门与事件契约。

全部离线：用脚本化的假模型驱动，不需要 LLM、不需要网络、不碰 Windows API。
checkpointer 一律用内存，避免往真实的 data/ 目录写 SQLite。
"""
from __future__ import annotations

import json
import sys
import uuid
from unittest.mock import MagicMock

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.types import Command
from pydantic import ConfigDict

# agent.tools 在模块层 import ctypes —— 必须先 mock
_mock_ctypes = MagicMock()
_mock_ctypes.windll = MagicMock()
_mock_ctypes.windll.shell32 = MagicMock()
_mock_ctypes.windll.shell32.IsUserAnAdmin = MagicMock(return_value=False)
_mock_ctypes.windll.kernel32 = MagicMock()
_mock_ctypes.wintypes = MagicMock()
_mock_ctypes.Structure = type
sys.modules["ctypes"] = _mock_ctypes

from agent.config import AgentConfig  # noqa: E402
from agent.graph import (  # noqa: E402
    build_graph,
    extract_interrupts,
    needs_approval,
    recursion_limit_for,
    resolve_approval_mode,
)
from agent.tools import ToolDef, ToolRegistry  # noqa: E402

# ---- 测试替身 ----

class ScriptedChatModel(BaseChatModel):
    """按脚本依次返回 AIMessage；记录每次收到的 prompt 供断言。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    script: list = []
    calls: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        # 图测试不关心 schema 传递（那是 test_graph_model 的职责）
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self.script) - 1)
        src = self.script[idx]
        # 每次返回**新 id 的副本**：add_messages 会按 id 去重，若反复塞同一个实例，
        # 第二条 AI 消息会被当作「原地更新」而不是追加，最后一条就成了 ToolMessage，
        # 路由随即读到「没有 tool_calls」而提前 END。真实模型每次都是新消息。
        fresh = AIMessage(
            content=src.content,
            tool_calls=[dict(tc) for tc in (src.tool_calls or [])],
            id=uuid.uuid4().hex,
        )
        return ChatResult(generations=[ChatGeneration(message=fresh)])


class StreamingScriptedModel(ScriptedChatModel):
    """把脚本文本按字符切开逐块吐出，用来验证事件契约支持增量。"""

    @property
    def _llm_type(self) -> str:
        return "scripted-streaming"

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        src = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        text = src.content if isinstance(src.content, str) else ""
        for ch in text:
            yield ChatGenerationChunk(message=AIMessageChunk(content=ch))
        if src.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="", tool_calls=[dict(tc) for tc in src.tool_calls]))


def ai_tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def make_config(**overrides) -> AgentConfig:
    base = dict(
        providers=[], max_iterations=5, mcp_servers=[], skill_dirs=[],
        knowledge_base_enabled=False, checkpoint_backend="memory",
        approval_mode="interactive",
    )
    base.update(overrides)
    return AgentConfig(**base)


def make_registry(run_command_handler=None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolDef(
        name="scan_network", description="scan", parameters={},
        handler=lambda: {"suspicious": 0},
    ))
    registry.register(ToolDef(
        name="run_command", description="run", parameters={"command": {"type": "string"}},
        handler=run_command_handler or (lambda command: {"ok": command}),
        requires_approval=True, risk_level="caution",
    ))
    return registry


# ---- 驱动辅助 ----

class Harness:
    """把「跑图 / 处理中断 / 恢复」这套重复动作收在一处。"""

    def __init__(self, config, registry, script, thread_id="t-test",
                 model_cls=ScriptedChatModel):
        self.config = config
        self.registry = registry
        self.model = model_cls(script=script)
        self.app = build_graph(config, registry, self.model)
        self.state_config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": recursion_limit_for(config),
        }
        self.events: list[dict] = []

    def _consume(self, payload):
        interrupts = []
        for part in self.app.stream(
            payload, self.state_config,
            stream_mode=["updates", "custom"], version="v2",
        ):
            if part["type"] == "custom":
                self.events.append(part["data"])
            elif part["type"] == "updates":
                interrupts.extend(extract_interrupts(part["data"]))
        return interrupts

    def run(self, user_input: str, decisions: list | None = None):
        """跑一轮；遇到审批中断就按 decisions 依次恢复。"""
        decisions = list(decisions or [])
        interrupts = self._consume({
            "messages": [HumanMessage(content=user_input)],
            "user_input": user_input,
        })
        asked = []
        while interrupts:
            asked.extend(i.value for i in interrupts)
            decision = decisions.pop(0) if decisions else {"approved": False}
            interrupts = self._consume(Command(resume=decision))
        return asked

    def events_of(self, etype: str, name: str | None = None) -> list[dict]:
        out = [e for e in self.events if e.get("type") == etype]
        if name is not None:
            out = [e for e in out if e.get("name") == name]
        return out

    def final_text(self) -> str:
        return self.app.get_state(self.state_config).values.get("final_text", "")


# ---- 用例 ----

class TestBasicLoop:
    def test_single_turn_no_tools(self):
        h = Harness(make_config(), make_registry(), [AIMessage(content="一切正常")])
        asked = h.run("你好")
        assert asked == []
        assert h.events_of("text") == [{"type": "text", "content": "一切正常"}]
        assert h.events_of("tool_start") == []
        assert h.final_text() == "一切正常"

    def test_tool_then_answer(self):
        h = Harness(
            make_config(), make_registry(),
            [ai_tool_call("scan_network", {}), AIMessage(content="没有可疑连接")],
        )
        h.run("扫描网络")

        assert [e["type"] for e in h.events] == ["tool_start", "tool_result", "text"]
        assert h.events_of("tool_start", "scan_network")[0]["arguments"] == {}
        assert h.final_text() == "没有可疑连接"

        # 第二次 LLM 调用必须能看到工具结果：prompt 里最后一条是 ToolMessage
        second_prompt = h.model.calls[1]
        assert second_prompt[-1].type == "tool"
        assert second_prompt[-1].tool_call_id == "c1"
        assert json.loads(second_prompt[-1].content) == {"suspicious": 0}

    def test_iteration_cap_produces_fallback_text(self):
        """模型永远要求调工具时必须被语义上限截断，而不是抛 GraphRecursionError。"""
        config = make_config(max_iterations=3)
        # 脚本用尽后会重复最后一条 -> 无限要求调工具
        h = Harness(config, make_registry(), [ai_tool_call("scan_network", {})])
        h.run("死循环")
        assert len(h.model.calls) == 3
        assert h.events_of("text")[-1]["content"] == "[Max iterations reached]"


class TestApprovalGate:
    def test_approval_approved_executes_once(self):
        """⚠ 守门用例：审批节点重放时绝不能让工具被执行两次。"""
        handler = MagicMock(return_value={"ok": True})
        h = Harness(
            make_config(), make_registry(handler),
            [ai_tool_call("run_command", {"command": "ipconfig"}),
             AIMessage(content="已执行")],
        )
        asked = h.run("跑一下 ipconfig", decisions=[{"approved": True}])

        # 中断载荷内容正确
        assert len(asked) == 1
        assert asked[0]["tool"] == "run_command"
        assert asked[0]["arguments"] == {"command": "ipconfig"}
        assert asked[0]["risk_level"] == "caution"

        # 副作用恰好一次
        assert handler.call_count == 1
        assert handler.call_args.kwargs == {"command": "ipconfig"}
        # 事件也必须只出现一次（重放会让 UI 重复画出工具调用）
        assert len(h.events_of("tool_start", "run_command")) == 1
        assert len(h.events_of("tool_result", "run_command")) == 1

    def test_approval_rejected_feeds_tool_result(self):
        """拒绝不抛异常：作为正常工具结果回给模型，图照常走到 END。"""
        handler = MagicMock(return_value={"ok": True})
        h = Harness(
            make_config(), make_registry(handler),
            [ai_tool_call("run_command", {"command": "ipconfig"}),
             AIMessage(content="那我换个方式")],
        )
        h.run("跑一下 ipconfig", decisions=[{"approved": False, "reason": "gui_denied"}])

        assert handler.call_count == 0
        assert h.events_of("tool_start", "run_command") == []

        # 模型看到的是 rejected_by_user 的 ToolMessage
        tool_msg = h.model.calls[1][-1]
        assert tool_msg.type == "tool"
        payload = json.loads(tool_msg.content)
        assert payload["status"] == "rejected_by_user"
        assert payload["reason"] == "gui_denied"
        assert "不要重试" in payload["message"]

        assert h.final_text() == "那我换个方式"

    def test_auto_reject_fails_closed(self):
        """无人在场时降级为拒绝，而不是自动放行。"""
        handler = MagicMock(return_value={"ok": True})
        h = Harness(
            make_config(approval_mode="auto_reject"), make_registry(handler),
            [ai_tool_call("run_command", {"command": "ipconfig"}),
             AIMessage(content="好的")],
        )
        asked = h.run("跑一下")
        assert asked == []            # 根本没弹
        assert handler.call_count == 0
        assert json.loads(h.model.calls[1][-1].content)["status"] == "rejected_by_user"

    def test_auto_approve_runs_without_asking(self):
        handler = MagicMock(return_value={"ok": True})
        h = Harness(
            make_config(approval_mode="auto_approve"), make_registry(handler),
            [ai_tool_call("run_command", {"command": "ipconfig"}),
             AIMessage(content="已执行")],
        )
        asked = h.run("跑一下")
        assert asked == []
        assert handler.call_count == 1

    def test_ungated_tool_never_asks(self):
        h = Harness(
            make_config(approval_mode="auto_reject"), make_registry(),
            [ai_tool_call("scan_network", {}), AIMessage(content="ok")],
        )
        assert h.run("扫描") == []
        assert len(h.events_of("tool_start", "scan_network")) == 1

    def test_two_gated_calls_ask_one_at_a_time(self):
        """一次响应里两个敏感调用 -> 串行问两次，而不是一次问两个。"""
        handler = MagicMock(return_value={"ok": True})
        two_calls = AIMessage(content="", tool_calls=[
            {"name": "run_command", "args": {"command": "ipconfig"},
             "id": "c1", "type": "tool_call"},
            {"name": "run_command", "args": {"command": "netstat"},
             "id": "c2", "type": "tool_call"},
        ])
        h = Harness(
            make_config(), make_registry(handler),
            [two_calls, AIMessage(content="都执行了")],
        )
        asked = h.run("两条都跑", decisions=[{"approved": True}, {"approved": False}])
        assert [a["arguments"]["command"] for a in asked] == ["ipconfig", "netstat"]
        assert handler.call_count == 1
        assert handler.call_args.kwargs == {"command": "ipconfig"}


class TestApprovalPolicy:
    def test_needs_approval_from_tool_flag(self):
        config, registry = make_config(), make_registry()
        assert needs_approval("run_command", config, registry) is True
        assert needs_approval("scan_network", config, registry) is False

    def test_config_list_adds_tools(self):
        config = make_config(approval_required_tools=["scan_network"])
        assert needs_approval("scan_network", config, make_registry()) is True

    def test_resolve_mode_respects_explicit_setting(self):
        assert resolve_approval_mode(make_config(approval_mode="auto_approve")) == "auto_approve"
        assert resolve_approval_mode(make_config(approval_mode="auto_reject")) == "auto_reject"

    def test_resolve_mode_downgrades_without_tty(self):
        """配置说 interactive 但没有可交互 stdin -> fail-closed 到拒绝。"""
        config = make_config(approval_mode="interactive")
        assert resolve_approval_mode(config, interactive_available=False) == "auto_reject"
        assert resolve_approval_mode(config, interactive_available=True) == "interactive"


class TestStreamingContract:
    """流式路径下事件契约保持不变：仍是 {type: text, content: <增量>}。

    只是从「一次给整段」变成「分多次给增量」—— CLI 顺序写出即得全文，
    GUI 累积后渲染即打字机效果，两边都不用改。
    """

    def test_text_arrives_as_multiple_events(self):
        h = Harness(make_config(), make_registry(), [AIMessage(content="安全")],
                    model_cls=StreamingScriptedModel)
        h.run("状态如何")
        texts = [e["content"] for e in h.events_of("text")]
        assert len(texts) > 1, "文本应分多次吐出，而不是一次性整段"
        assert "".join(texts) == "安全"
        assert h.final_text() == "安全"

    def test_streamed_tool_calls_still_route_to_approval(self):
        """流式返回的 tool_calls 也要能正常触发审批闸门。"""
        handler = MagicMock(return_value={"ok": True})
        h = Harness(
            make_config(), make_registry(handler),
            [ai_tool_call("run_command", {"command": "ipconfig"}),
             AIMessage(content="done")],
            model_cls=StreamingScriptedModel,
        )
        asked = h.run("跑一下", decisions=[{"approved": True}])
        assert [a["tool"] for a in asked] == ["run_command"]
        assert handler.call_count == 1


class TestRecursionLimit:
    def test_gives_headroom_over_semantic_cap(self):
        """必须显著高于 2*max_iterations+3，否则语义闸门还没响框架就先炸了。"""
        config = make_config(max_iterations=10)
        assert recursion_limit_for(config) > 2 * 10 + 3
        assert recursion_limit_for(config) > 25  # LangGraph 默认值
