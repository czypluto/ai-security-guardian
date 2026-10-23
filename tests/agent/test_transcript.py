"""TranscriptStore 测试：append-only、幂等、回查、损坏行容错。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from agent.transcript import TranscriptStore  # noqa: E402


def _turn(text: str):
    return [
        HumanMessage(content=text),
        AIMessage(content="", tool_calls=[{
            "name": "scan_network", "args": {}, "id": f"call-{text}",
            "type": "tool_call",
        }]),
        ToolMessage(content=f"result for {text}", tool_call_id=f"call-{text}",
                    name="scan_network"),
        AIMessage(content=f"answer for {text}"),
    ]


def test_append_and_load(tmp_path):
    store = TranscriptStore(str(tmp_path))
    assert store.append_turn("conv-1", "t-1", _turn("防火墙")) is True
    assert store.append_turn("conv-1", "t-2", _turn("端口")) is True

    turns = store.load_turns("conv-1")
    assert [t["turn_id"] for t in turns] == ["t-1", "t-2"]
    assert turns[0]["conversation_id"] == "conv-1"


def test_duplicate_turn_is_idempotent(tmp_path):
    store = TranscriptStore(str(tmp_path))
    assert store.append_turn("conv-1", "t-1", _turn("x")) is True
    assert store.append_turn("conv-1", "t-1", _turn("x")) is False
    assert len(store.load_turns("conv-1")) == 1


def test_load_messages_roundtrip(tmp_path):
    store = TranscriptStore(str(tmp_path))
    store.append_turn("conv-1", "t-1", _turn("防火墙"))
    messages = store.load_messages("conv-1")
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "防火墙"
    assert any(isinstance(m, ToolMessage) for m in messages)


def test_search_returns_matching_turn(tmp_path):
    store = TranscriptStore(str(tmp_path))
    store.append_turn("conv-1", "t-1", _turn("怎么查看防火墙状态"))
    store.append_turn("conv-1", "t-2", _turn("勒索软件怎么排查"))

    hits = store.search("conv-1", "防火墙", limit=3)
    assert hits
    assert hits[0]["turn_id"] == "t-1"


def test_invalid_conversation_id_rejected(tmp_path):
    store = TranscriptStore(str(tmp_path))
    try:
        store.append_turn("../escape", "t-1", _turn("x"))
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("非法 conversation_id 应被拒绝")


def test_corrupt_line_is_skipped(tmp_path):
    store = TranscriptStore(str(tmp_path))
    store.append_turn("conv-1", "t-1", _turn("ok"))
    path = tmp_path / "conv-1.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write("{not json}\n")

    turns = store.load_turns("conv-1")
    assert len(turns) == 1
    assert turns[0]["turn_id"] == "t-1"
