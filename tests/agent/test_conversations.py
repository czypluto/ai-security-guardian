"""ConversationIndex 测试：创建、更新、排序与持久化。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.conversations import ConversationIndex, title_from_messages  # noqa: E402


def test_create_get_and_list(tmp_path):
    index = ConversationIndex(str(tmp_path))
    index.create("conv-1", "guardian-conv-1", title="防火墙")
    index.create("conv-2", "guardian-conv-2", title="端口")

    meta = index.get("conv-1")
    assert meta is not None
    assert meta.thread_id == "guardian-conv-1"
    assert {m.conversation_id for m in index.list()} == {"conv-1", "conv-2"}


def test_record_turn_updates_count_and_title(tmp_path):
    index = ConversationIndex(str(tmp_path))
    index.create("conv-1", "guardian-conv-1")
    index.record_turn("conv-1", 4, title="第一个问题")

    meta = index.get("conv-1")
    assert meta.message_count == 4
    assert meta.title == "第一个问题"

    # 重复记录不会覆盖已有标题
    index.record_turn("conv-1", 2, title="另一个标题")
    meta = index.get("conv-1")
    assert meta.message_count == 6
    assert meta.title == "第一个问题"


def test_persists_across_instances(tmp_path):
    first = ConversationIndex(str(tmp_path))
    first.create("conv-1", "guardian-conv-1", title="持久化")
    first.update("conv-1", message_count=3)

    second = ConversationIndex(str(tmp_path))
    meta = second.get("conv-1")
    assert meta is not None
    assert meta.title == "持久化"
    assert meta.message_count == 3


def test_missing_id_returns_none(tmp_path):
    index = ConversationIndex(str(tmp_path))
    assert index.get("nope") is None
    assert index.update("nope", title="x") is None


def test_title_from_messages():
    from langchain_core.messages import AIMessage, HumanMessage
    assert title_from_messages([
        AIMessage(content="先说话"),
        HumanMessage(content="  多行\n问题  "),
    ]) == "多行 问题"
    assert title_from_messages([]) == ""
