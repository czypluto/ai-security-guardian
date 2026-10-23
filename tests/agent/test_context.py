"""上下文预算工具测试：token 估算、安全窗口、工具结果压缩。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from agent.context import (  # noqa: E402
    compact_tool_messages,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    safe_recent_window,
    select_compression_cut,
)


def _tool_turn(turn_id: str, result: str = "ok"):
    """一个包含 tool_call + ToolMessage 的完整 turn。"""
    return [
        HumanMessage(content=f"用户问题 {turn_id}"),
        AIMessage(content="", tool_calls=[{
            "name": "scan_network", "args": {}, "id": f"call-{turn_id}",
            "type": "tool_call",
        }]),
        ToolMessage(content=result, tool_call_id=f"call-{turn_id}", name="scan_network"),
        AIMessage(content=f"回答 {turn_id}"),
    ]


# ---- token 估算 ----

def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0


def test_estimate_tokens_chinese_is_not_underestimated():
    text = "这是一个中文句子" * 10
    assert estimate_tokens(text) >= len(text)  # 中文按 >=1 token/字


def test_estimate_messages_includes_tool_calls():
    msg = AIMessage(content="", tool_calls=[{
        "name": "scan_network", "args": {"x": 1}, "id": "c1", "type": "tool_call",
    }])
    assert estimate_message_tokens(msg) > 0
    assert estimate_messages_tokens([msg]) == estimate_message_tokens(msg)


# ---- 安全窗口 ----

def test_window_starts_on_turn_boundary_and_keeps_current_turn():
    messages = _tool_turn("1") + _tool_turn("2") + _tool_turn("3")
    # 预算极小：只能保留最少 turn（当前 turn）
    window = safe_recent_window(messages, max_tokens=10, min_recent_turns=1)
    assert window
    assert isinstance(window[0], HumanMessage)
    assert window[-1].content == "回答 3"


def test_window_keeps_at_least_min_recent_turns():
    messages = _tool_turn("1") + _tool_turn("2") + _tool_turn("3")
    window = safe_recent_window(messages, max_tokens=1, min_recent_turns=2)
    assert isinstance(window[0], HumanMessage)
    # 至少包含 turn 2 和 turn 3
    humans = [m.content for m in window if isinstance(m, HumanMessage)]
    assert humans == ["用户问题 2", "用户问题 3"]


def test_window_never_starts_with_tool_message():
    messages = _tool_turn("1", result="x" * 500) + _tool_turn("2", result="y" * 500)
    for budget in (1, 10, 100, 1000, 100000):
        window = safe_recent_window(messages, max_tokens=budget, min_recent_turns=1)
        assert not isinstance(window[0], ToolMessage)


def test_window_large_budget_keeps_everything():
    messages = _tool_turn("1") + _tool_turn("2")
    assert safe_recent_window(messages, max_tokens=100000, min_recent_turns=1) == messages


# ---- 压缩切点 ----

def test_compression_cut_never_cuts_current_turn():
    messages = _tool_turn("1") + _tool_turn("2")
    cut = select_compression_cut(
        messages, compressed_through=0, max_recent_tokens=1, min_recent_turns=1)
    # cut 必须落在 turn 边界；允许切到当前 turn 的起点之前，但不能切进当前 turn
    assert cut in (0, len(messages) - 4)
    assert isinstance(messages[cut], HumanMessage)
    assert cut <= len(messages) - 4


def test_compression_cut_advances_when_budget_is_tight():
    messages = _tool_turn("1") + _tool_turn("2") + _tool_turn("3")
    cut = select_compression_cut(
        messages, compressed_through=0, max_recent_tokens=10, min_recent_turns=1)
    assert isinstance(messages[cut], HumanMessage)
    assert cut >= 4  # 至少压掉 turn 1


# ---- 工具结果压缩 ----

def test_compact_tool_messages_truncates_but_keeps_identity():
    original = ToolMessage(
        content="a" * 1000, tool_call_id="call-1", name="scan_network")
    compacted = compact_tool_messages([original], max_chars=100)[0]

    assert len(compacted.content) < len(original.content)
    assert "truncated" in compacted.content
    assert compacted.tool_call_id == "call-1"
    assert compacted.name == "scan_network"
    # 原对象不被修改
    assert len(original.content) == 1000


def test_compact_short_tool_message_unchanged():
    msg = ToolMessage(content="short", tool_call_id="c", name="t")
    assert compact_tool_messages([msg], max_chars=100)[0] is msg
