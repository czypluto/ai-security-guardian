"""LangGraph 适配层 —— 把自研 LLMRouter 包成 LangChain BaseChatModel。

为什么需要这一层：LangGraph 的 `bind_tools`、消息模式、checkpointer 的中断恢复，
都建立在 langchain-core 的 `BaseMessage` / `BaseChatModel` 契约上；
而本项目的 LLM 客户端（`agent/llm.py`）是自研的 requests 直连 OpenAI 兼容协议，
带着多 provider 故障转移与离线冷却。

**包一层比替换掉它划算得多**：`_generate` 只做一次 `self.router.chat(...)` 转发，
于是故障转移、30s 离线冷却、`_provider`/`_latency_ms` 元数据全部原样保留 ——
既没有复制那段逻辑，也没有绕过它。换来的只是让图认得这些消息。

刻意**不**实现 `_stream`：`LLMRouter.chat_stream` 没有故障转移（只取 `_active_idx`
那一个 provider）、不返回延迟元数据、tool_calls 也是凑齐 finish_reason 才吐，
接进来等于给 GUI 换一条更差的通道。逐 token 流式留作后续单独议题。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict

logger = logging.getLogger("Guardian.GraphModel")


class LLMUnavailableError(RuntimeError):
    """所有 provider 都失败（LLMRouter.chat 返回 _ok=False）。

    由 ``AgentCore.run_stream`` 捕获后转成 ``{"type": "error"}`` 事件 ——
    保持与改造前 core.py 完全一致的对外行为。
    """


# ---- 消息互转（纯函数，可单独单测）----

def _stringify(content: Any) -> str:
    """LangChain 的 content 可能是 str，也可能是多模态 block 列表；OpenAI 要 str。"""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(part.get("text", ""))
        return "".join(parts)
    return str(content)


def _safe_json(raw: Any) -> dict:
    """解析 tool_call 的 arguments；失败给 {}（与 llm.py 的既有容错一致）。"""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def messages_to_dicts(messages: Sequence[BaseMessage]) -> list[dict]:
    """BaseMessage -> OpenAI 风格 dict（`agent/llm.py` 期待的形态）。"""
    out: list[dict] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            out.append({"role": "system", "content": _stringify(m.content)})
        elif isinstance(m, HumanMessage):
            out.append({"role": "user", "content": _stringify(m.content)})
        elif isinstance(m, ToolMessage):
            out.append({
                "role": "tool",
                "tool_call_id": m.tool_call_id,
                "content": _stringify(m.content),
            })
        elif isinstance(m, AIMessage):
            msg: dict[str, Any] = {"role": "assistant", "content": _stringify(m.content)}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("args") or {},
                                                   ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]
            out.append(msg)
        else:
            # 未知消息类型：退化成 user，至少不丢内容
            out.append({"role": "user", "content": _stringify(getattr(m, "content", ""))})
    return out


def dicts_to_messages(msgs: Sequence[dict]) -> list[BaseMessage]:
    """OpenAI 风格 dict -> BaseMessage（GUI 的历史是纯 dict，进图前要转换）。"""
    out: list[BaseMessage] = []
    for m in msgs:
        role = m.get("role", "")
        content = m.get("content") or ""
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role in ("user", "human"):
            out.append(HumanMessage(content=content))
        elif role in ("assistant", "ai", "bot", "model"):
            tool_calls = []
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                tool_calls.append({
                    "name": fn.get("name", ""),
                    "args": _safe_json(fn.get("arguments")),
                    "id": tc.get("id", ""),
                    "type": "tool_call",
                })
            out.append(AIMessage(content=content, tool_calls=tool_calls))
        elif role == "tool":
            out.append(ToolMessage(content=content,
                                   tool_call_id=m.get("tool_call_id", "")))
    return out


def response_to_ai_message(resp: dict) -> AIMessage:
    """LLMRouter.chat 的返回 -> AIMessage（含 provider/延迟元数据）。"""
    try:
        choice = resp["choices"][0]
    except (KeyError, IndexError, TypeError):
        return AIMessage(content="")

    msg = choice.get("message") or {}
    tool_calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        tool_calls.append({
            "name": fn.get("name", ""),
            "args": _safe_json(fn.get("arguments")),
            "id": tc.get("id", ""),
            "type": "tool_call",
        })

    return AIMessage(
        content=msg.get("content") or "",
        tool_calls=tool_calls,
        # 保留路由元数据：排查「这一轮走的哪个 provider / 多慢」时要用
        additional_kwargs={
            "_provider": resp.get("_provider"),
            "_latency_ms": resp.get("_latency_ms"),
        },
        response_metadata={
            "provider": resp.get("_provider"),
            "latency_ms": resp.get("_latency_ms"),
            "finish_reason": choice.get("finish_reason"),
        },
    )


# ---- 模型 ----

class GuardianChatModel(BaseChatModel):
    """LLMRouter 的 LangChain 外观。只拦截调用，不重写路由逻辑。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # 注意：pydantic 模型字段不能以下划线开头
    router: Any
    max_tokens: int = 1024
    temperature: float = 0.7
    tool_choice: str = "auto"
    bound_tools: Optional[list[dict]] = None

    @property
    def _llm_type(self) -> str:
        return "guardian-router"

    @property
    def _identifying_params(self) -> dict:
        provider = getattr(self.router, "active_provider", None)
        return {"provider": getattr(provider, "name", "none"),
                "model": getattr(provider, "model", "none")}

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        """覆写基类实现：已经是 OpenAI schema dict 的直接用，不走转换。

        `ToolDef.to_openai_schema()` 产出的就是合规的 function schema，
        经 `convert_to_openai_tool` 绕一圈只会归一化 `required` 等字段 —— 无收益且可能变形。
        """
        schemas: list[dict] = []
        for t in tools:
            if isinstance(t, dict):
                schemas.append(t)
            else:
                from langchain_core.utils.function_calling import convert_to_openai_tool
                schemas.append(convert_to_openai_tool(t))
        return self.bind(tools=schemas, tool_choice=tool_choice or self.tool_choice)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        tools = kwargs.get("tools", self.bound_tools)
        tool_choice = kwargs.get("tool_choice", self.tool_choice)

        resp = self.router.chat(
            messages=messages_to_dicts(messages),
            tools=list(tools) if tools else None,
            tool_choice=tool_choice,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        if not resp.get("_ok"):
            # 全部 provider 都挂了 —— 交给上层转成 error 事件，而不是让图崩掉
            raise LLMUnavailableError(resp.get("_error", "LLM call failed"))

        return ChatResult(
            generations=[ChatGeneration(message=response_to_ai_message(resp))]
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ):
        """逐 token 流式。

        这条路径**没有多 provider 故障转移** —— ``LLMRouter.chat_stream`` 只取
        ``_active_idx`` 那一个 provider，不像 ``chat`` 会轮询换人、也会跳过冷却中的
        provider。所以这里保留了兜底：**首字未出就失败**时退回 ``_generate``，
        让 ``LLMRouter.chat`` 去做它该做的故障转移。一旦已经吐过内容就不再回退 ——
        重来一遍会让用户看到重复文本。

        tool_calls 由 ``chat_stream`` 在 finish_reason 处一次性吐出，这里把它包成
        末尾的一个 chunk；调用方用 ``+`` 累加即可得到完整的 AIMessage。
        """
        tools = kwargs.get("tools", self.bound_tools)

        saw_content = False
        tool_calls_raw: list[dict] = []
        stream_error = None

        for event in self.router.chat_stream(
            messages=messages_to_dicts(messages),
            tools=list(tools) if tools else None,
            max_tokens=self.max_tokens,
        ):
            etype = event.get("type", "")
            if etype == "text":
                saw_content = True
                piece = event.get("content", "")
                if run_manager:
                    run_manager.on_llm_new_token(piece)
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
            elif etype == "tool_call":
                tool_calls_raw.append(event.get("tool_call") or {})
            elif etype == "error":
                stream_error = event.get("content", "AI 服务异常")
                break

        if stream_error and not saw_content and not tool_calls_raw:
            # 逐字尚未开始 -> 回退到 invoke 路径，把故障转移拿回来
            result = self._generate(messages, stop, run_manager, **kwargs)
            for gen in result.generations:
                yield ChatGenerationChunk(message=_to_chunk(gen.message))
            return

        if tool_calls_raw:
            chunks = []
            for i, tc in enumerate(tool_calls_raw):
                fn = tc.get("function") or {}
                chunks.append({
                    "name": fn.get("name", ""),
                    "args": fn.get("arguments") or "{}",
                    "id": tc.get("id", ""),
                    "index": i,          # 显式给 index，累加时不会互相吞掉
                    "type": "tool_call_chunk",
                })
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_call_chunks=chunks))


def _to_chunk(message: BaseMessage) -> AIMessageChunk:
    """把完整消息转成可累加的 chunk（回退路径用）。"""
    if isinstance(message, AIMessageChunk):
        return message
    tool_calls = list(getattr(message, "tool_calls", None) or [])
    return AIMessageChunk(
        content=_stringify(getattr(message, "content", "")),
        tool_calls=tool_calls,
    )


def build_chat_model(router, config=None) -> GuardianChatModel:
    """工厂。`agent/core.py` 以同名模块级函数引用它，作为测试注入的缝。"""
    return GuardianChatModel(router=router, max_tokens=1024, temperature=0.7)
