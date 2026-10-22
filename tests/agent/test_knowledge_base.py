"""KnowledgeBase 测试：纯 BM25 检索、Markdown 事实源、索引失效与后台线程。

不依赖任何嵌入服务或向量库——本项目的知识库就是 Markdown + 中文 BM25。
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.knowledge_base import KnowledgeBase  # noqa: E402

MESSAGES = [
    {"role": "user", "content": "我的防火墙开着吗"},
    {"role": "assistant", "content": "防火墙开启中，一切正常"},
]


def _kb(tmp_path) -> KnowledgeBase:
    return KnowledgeBase(persist_dir=str(tmp_path))


def test_markdown_is_the_source_of_truth(tmp_path):
    kb = _kb(tmp_path)
    conv_id = kb.add_conversation(MESSAGES)

    assert conv_id is not None
    assert (tmp_path / "conversations" / f"{conv_id}.md").exists()
    assert kb.conversation_count == 1


def test_search_hits_chinese_terms(tmp_path):
    kb = _kb(tmp_path)
    kb.add_conversation(MESSAGES)

    hits = kb.search("防火墙")
    assert hits
    assert "防火墙" in hits[0]["text"]
    assert hits[0]["metadata"]["conversation_id"]


def test_empty_query_returns_empty(tmp_path):
    kb = _kb(tmp_path)
    kb.add_conversation(MESSAGES)
    assert kb.search("") == []


def test_index_is_invalidated_after_adding_conversation(tmp_path):
    kb = _kb(tmp_path)
    kb.add_conversation(MESSAGES)
    assert len(kb._ensure_bm25_index()) == 1

    kb.add_conversation([
        {"role": "user", "content": "怎么查看监听端口"},
        {"role": "assistant", "content": "用 netstat -ano"},
    ])
    # 新增对话后索引应重建，而不是继续用旧的一份
    assert len(kb._ensure_bm25_index()) == 2


def test_rebuild_index_resets_then_rebuilds(tmp_path):
    kb = _kb(tmp_path)
    kb.add_conversation(MESSAGES)
    first = kb._ensure_bm25_index()

    kb.rebuild_index()
    assert kb._bm25 is None
    second = kb._ensure_bm25_index()
    assert second is not first
    assert len(second) == 1


def test_delete_conversation_removes_markdown_and_invalidates_index(tmp_path):
    kb = _kb(tmp_path)
    conv_id = kb.add_conversation(MESSAGES)
    kb._ensure_bm25_index()

    kb.delete_conversation(conv_id)
    assert not (tmp_path / "conversations" / f"{conv_id}.md").exists()
    assert kb._bm25 is None
    assert kb.search("防火墙") == []


def test_stats_shape(tmp_path):
    kb = _kb(tmp_path)
    kb.add_conversation(MESSAGES)

    stats = kb.get_stats()
    assert stats["conversations"] == 1
    assert stats["bm25_chunks"] == 1
    assert "storage_dir" in stats
    # 向量相关字段已随迁移移除
    assert "vector_count" not in stats
    assert "embedding_type" not in stats


def test_kb_usable_from_background_thread(tmp_path):
    """回归：索引构建与检索必须能在后台线程安全执行。"""
    kb = _kb(tmp_path)
    errors = []

    def run():
        try:
            conv_id = kb.add_conversation(MESSAGES)
            hits = kb.search("防火墙")
            assert conv_id is not None
            assert isinstance(hits, list)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=10)
    assert not errors
    assert kb.conversation_count == 1
