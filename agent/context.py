"""上下文预算工具 —— token 估算、安全窗口、工具结果压缩。

这里的函数都是**纯函数**，不碰模型、不碰磁盘，方便单测和复用。

设计约束:
  - 窗口只能从 HumanMessage（turn 边界）开始切，绝不切断
    AIMessage(tool_calls) 与 ToolMessage 的配对；
  - 当前 turn 永不压缩/裁掉；
  - token 估算不依赖 tokenizer（项目没有引入），用保守的字符启发式：
    中文约 1 token/字，其它字符约 4 字符/token。宁可高估，不要低估。
"""
from __future__ import annotations

import json
import math
from typing import Any, List, Sequence

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    ToolMessage,
)


def _content_text(content: Any) -> str:
    """把消息 content 拍平成字符串（兼容多模态 block 列表）。"""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return str(content)


def estimate_tokens(text: str) -> int:
    """保守估算 token 数。

    中文按 1 字 ≈ 1 token，其它按 4 字符 ≈ 1 token。
    实测 DeepSeek 对中文大约 0.6~1 token/字，这里取偏高的值，避免低估。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "㐀" <= ch <= "鿿")
    other = len(text) - cjk
    return cjk + math.ceil(other / 4)


def message_text(message: BaseMessage) -> str:
    """消息的完整可计数文本，包含 tool_calls 的 JSON。"""
    text = _content_text(getattr(message, "content", ""))
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        text += "\n" + json.dumps(tool_calls, ensure_ascii=False)
    return text


def estimate_message_tokens(message: BaseMessage) -> int:
    return estimate_tokens(message_text(message))


def estimate_messages_tokens(messages: Sequence[BaseMessage]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


def estimate_tools_tokens(schemas: Sequence[dict]) -> int:
    """工具 schema 每次请求都会发送，必须计入预算。"""
    if not schemas:
        return 0
    return estimate_tokens(json.dumps(list(schemas), ensure_ascii=False))


def compact_tool_messages(messages: Sequence[BaseMessage],
                          max_chars: int = 4000) -> List[BaseMessage]:
    """返回一份“给模型看”的消息副本，把过长的 ToolMessage 截断。

    原始 ToolMessage 不变（state / transcript 里仍保留完整结果），
    只有构建 prompt 和估算 token 时使用压缩副本。
    """
    if max_chars <= 0:
        return list(messages)

    out: List[BaseMessage] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            text = _content_text(message.content)
            if len(text) > max_chars:
                truncated = (text[:max_chars]
                             + f"\n...[truncated {len(text) - max_chars} chars]")
                out.append(message.model_copy(update={"content": truncated}))
                continue
        out.append(message)
    return out


def turn_starts(messages: Sequence[BaseMessage]) -> List[int]:
    """每个 turn 的起始下标（以 HumanMessage 为边界）。"""
    return [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]


def safe_recent_window(messages: Sequence[BaseMessage],
                       max_tokens: int,
                       min_recent_turns: int = 3) -> List[BaseMessage]:
    """按 turn 边界截取最近窗口，保持 tool_call / ToolMessage 配对完整。

    规则:
      - 窗口起点必须是 HumanMessage（turn 边界）；
      - 至少保留 ``min_recent_turns`` 个 turn（不足则全留）；
      - 当前 turn（最后一个 HumanMessage 之后）永远不切；
      - 找不到满足预算的切点时，返回最小保留窗口（可能仍超预算，
        由工具结果压缩和摘要来兜底）。
    """
    if not messages:
        return []
    if max_tokens <= 0:
        return []

    starts = turn_starts(messages)
    if not starts:
        # 没有 HumanMessage（例如异常状态）：不做结构性裁剪
        return list(messages)

    keep = max(1, min_recent_turns)
    # cut 必须 <= earliest_allowed，才能保证至少保留 keep 个 turn
    earliest_allowed = starts[max(0, len(starts) - keep)]

    for cut in starts:
        if cut > earliest_allowed:
            break
        window = list(messages[cut:])
        if estimate_messages_tokens(window) <= max_tokens:
            return window

    # 最小保留窗口都不满足预算：返回它，交给上层决定是否压缩工具结果
    return list(messages[earliest_allowed:])


def select_compression_cut(messages: Sequence[BaseMessage],
                           compressed_through: int,
                           max_recent_tokens: int,
                           min_recent_turns: int = 3) -> int:
    """选择“压缩到哪”：返回一个 turn 边界下标。

    保留 ``messages[cut:]`` 作为最近窗口，压缩 ``messages[compressed_through:cut]``。
    永远不切当前 turn（最后一个 HumanMessage 之后）。
    """
    if not messages:
        return 0
    starts = [i for i in turn_starts(messages) if i >= compressed_through]
    if not starts:
        return compressed_through

    current_start = starts[-1]
    keep = max(1, min_recent_turns)
    earliest_allowed = starts[max(0, len(starts) - keep)]

    for cut in starts:
        if cut > earliest_allowed:
            break
        if cut > current_start:
            # 不能把当前 turn 压掉；cut == current_start 合法（只保留当前 turn）
            continue
        window = compact_tool_messages(messages[cut:])
        if estimate_messages_tokens(window) <= max_recent_tokens:
            return cut

    # 没有满足预算的切点：至少保留 min_recent_turns，不压当前 turn。
    # 即使当前 turn 本身已超预算，也应把更早的 turn 压掉（那是唯一能做的事）。
    if earliest_allowed <= current_start:
        return earliest_allowed
    return compressed_through


