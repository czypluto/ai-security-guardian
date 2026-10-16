"""测试 agent/graph_model.py: GuardianChatModel 与消息互转。

可测性关键：适配层只是把 LLMRouter 包了一层，所以这里用假 router 就能
完整验证「消息转换 / tool_calls 解析 / 元数据保留 / 故障时不吞错」。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.graph_model import (
    GuardianChatModel,
    LLMUnavailableError,
    dicts_to_messages,
    messages_to_dicts,
)


class FakeRouter:
    """记录收到的参数，返回预设响应。不碰网络。"""

    def __init__(self, response=None):
        self.response = response or {
            "_ok": True,
            "_provider": "deepseek",
            "_latency_ms": 42.0,
            "choices": [{
                "message": {"content": "hello", "tool_calls": []},
                "finish_reason": "stop",
            }],
        }
        self.calls = []
        self.active_provider = None

    def chat(self, messages, tools=None, tool_choice="auto",
             max_tokens=1024, temperature=0.7, stream=False):
        self.calls.append({
            "messages": messages, "tools": tools,
            "tool_choice": tool_choice, "max_tokens": max_tokens,
        })
        return self.response


# ---- 消息互转 ----

class TestMessageConversion:
    def test_messages_to_dicts_roles(self):
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="hi"),
            AIMessage(content="thinking", tool_calls=[
                {"name": "scan_network", "args": {"deep": True},
                 "id": "c1", "type": "tool_call"}]),
            ToolMessage(content='{"ok": true}', tool_call_id="c1"),
        ]
        out = messages_to_dicts(msgs)
        assert [m["role"] for m in out] == ["system", "user", "assistant", "tool"]
        assert out[3]["tool_call_id"] == "c1"
        # tool_calls 必须还原成 OpenAI 的嵌套形态，arguments 是 JSON 字符串
        tc = out[2]["tool_calls"][0]
        assert tc["id"] == "c1"
        assert tc["function"]["name"] == "scan_network"
        assert tc["function"]["arguments"] == '{"deep": true}'

    def test_dicts_to_messages_roundtrip(self):
        original = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "c9", "content": "result"},
        ]
        msgs = dicts_to_messages(original)
        assert [type(m).__name__ for m in msgs] == [
            "SystemMessage", "HumanMessage", "ToolMessage"]
        assert msgs[2].tool_call_id == "c9"

    def test_multimodal_content_is_flattened(self):
        """content 为 block 列表时要拍平成字符串 —— OpenAI 只接受 str。"""
        msg = AIMessage(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        assert messages_to_dicts([msg])[0]["content"] == "ab"


# ---- 模型 ----

class TestGuardianChatModel:
    def test_generate_sends_dicts_and_keeps_tools_untouched(self):
        router = FakeRouter()
        model = GuardianChatModel(router=router)
        schemas = [{"type": "function", "function": {"name": "t", "description": "d",
                                                     "parameters": {"type": "object",
                                                                    "properties": {}}}}]
        model.bind_tools(schemas).invoke([HumanMessage(content="hi")])

        sent = router.calls[0]
        # 原样透传 —— 没有被 convert_to_openai_tool 归一化
        assert sent["tools"] == schemas
        assert sent["messages"] == [{"role": "user", "content": "hi"}]

    def test_generate_parses_tool_calls_and_metadata(self):
        router = FakeRouter({
            "_ok": True, "_provider": "zhipu", "_latency_ms": 12.5,
            "choices": [{
                "message": {"content": "", "tool_calls": [
                    {"id": "c1", "function": {"name": "run_command",
                                              "arguments": '{"command": "ipconfig"}'}}]},
                "finish_reason": "tool_calls",
            }],
        })
        result = GuardianChatModel(router=router).invoke([HumanMessage(content="run it")])
        assert result.tool_calls[0]["name"] == "run_command"
        assert result.tool_calls[0]["args"] == {"command": "ipconfig"}
        # provider / 延迟元数据必须活下来（排查「这轮走的哪个 provider」要用）
        assert result.additional_kwargs["_provider"] == "zhipu"
        assert result.response_metadata["latency_ms"] == 12.5

    def test_malformed_tool_arguments_degrade_to_empty_dict(self):
        """arguments 不是合法 JSON 时给 {}，不能让整轮炸掉。"""
        router = FakeRouter({
            "_ok": True,
            "choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "t", "arguments": "{not json"}}]},
                "finish_reason": "tool_calls"}],
        })
        result = GuardianChatModel(router=router).invoke([HumanMessage(content="x")])
        assert result.tool_calls[0]["args"] == {}

    def test_all_providers_down_raises_llm_unavailable(self):
        """故障转移全失败 -> 抛 LLMUnavailableError，由 run_stream 转成 error 事件。"""
        router = FakeRouter({"_ok": False, "_error": "deepseek: timeout"})
        with pytest.raises(LLMUnavailableError) as ei:
            GuardianChatModel(router=router).invoke([HumanMessage(content="x")])
        assert "timeout" in str(ei.value)

    def test_router_failover_is_not_bypassed(self):
        """适配层只调 router.chat —— 故障转移/冷却仍由 LLMRouter 负责。"""
        router = FakeRouter()
        model = GuardianChatModel(router=router)
        model.invoke([HumanMessage(content="x")])
        assert len(router.calls) == 1
        assert model._llm_type == "guardian-router"

    def test_max_tokens_from_construction(self):
        router = FakeRouter()
        GuardianChatModel(router=router, max_tokens=256).invoke([HumanMessage(content="x")])
        assert router.calls[0]["max_tokens"] == 256


class StreamingFakeRouter(FakeRouter):
    """额外提供 chat_stream 的假 router（yield 事件字典）。"""

    def __init__(self, events, response=None):
        super().__init__(response)
        self.events = events
        self.stream_calls = []

    def chat_stream(self, messages, tools=None, max_tokens=1024, temperature=0.7):
        self.stream_calls.append({"messages": messages, "tools": tools})
        for event in self.events:
            yield event


def _merge(chunks):
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    return merged


def _text(content):
    return {"type": "text", "content": content}


def _tool_call(name, args_json, call_id):
    return {"type": "tool_call", "tool_call": {
        "id": call_id, "function": {"name": name, "arguments": args_json}}}


class TestGuardianChatModelStream:
    """逐 token 流式路径。

    这条路径**没有多 provider 故障转移**（chat_stream 只取 _active_idx 那一个
    provider），所以「首字未出就失败时回退到 _generate」的兜底是它的安全网。
    """

    def test_yields_text_chunks_incrementally(self):
        router = StreamingFakeRouter([_text("He"), _text("llo")])
        chunks = list(GuardianChatModel(router=router).stream([HumanMessage(content="hi")]))

        # 关键：确实分了多次吐出，而不是一次性给整段
        assert [c.content for c in chunks if c.content] == ["He", "llo"]
        assert _merge(chunks).content == "Hello"
        # langchain 会在末尾补一个空 chunk（携带 usage 之类）；无害，
        # graph._stream_completion 只对非空内容发事件。这里断言它不携带文本。
        assert all(not c.content for c in chunks[2:])

    def test_tool_calls_arrive_as_one_final_chunk(self):
        router = StreamingFakeRouter([
            _text("thinking"),
            _tool_call("run_command", '{"command":"ipconfig"}', "c1"),
            _tool_call("scan_network", '{"deep":true}', "c2"),
        ])
        merged = _merge(list(GuardianChatModel(router=router).stream(
            [HumanMessage(content="hi")])))

        # 两个 tool call 不能互相吞掉 —— 所以 chunk 里显式给了 index
        assert [tc["name"] for tc in merged.tool_calls] == ["run_command", "scan_network"]
        assert merged.tool_calls[0]["args"] == {"command": "ipconfig"}
        assert merged.content == "thinking"

    def test_error_before_any_token_falls_back_to_generate(self):
        """首字未出就失败 -> 回退到 chat（那里才有故障转移）。"""
        router = StreamingFakeRouter([{"type": "error", "content": "boom"}])
        router.response = {
            "_ok": True,
            "choices": [{"message": {"content": "recovered"}}],
        }
        chunks = list(GuardianChatModel(router=router).stream([HumanMessage(content="hi")]))

        assert _merge(chunks).content == "recovered"
        assert len(router.calls) == 1, "没有回退到 _generate"

    def test_error_after_content_does_not_restart(self):
        """已经吐过字就不再回退 —— 重来一遍用户会看到重复文本。"""
        router = StreamingFakeRouter([_text("partial"), {"type": "error", "content": "boom"}])
        chunks = list(GuardianChatModel(router=router).stream([HumanMessage(content="hi")]))

        assert _merge(chunks).content == "partial"
        assert router.calls == [], "不该回退到 _generate"

    def test_bind_tools_schemas_reach_chat_stream(self):
        router = StreamingFakeRouter([_text("ok")])
        schemas = [{"type": "function", "function": {"name": "t", "description": "d",
                                                     "parameters": {"type": "object",
                                                                    "properties": {}}}}]
        list(GuardianChatModel(router=router).bind_tools(schemas).stream(
            [HumanMessage(content="hi")]))
        assert router.stream_calls[0]["tools"] == schemas
