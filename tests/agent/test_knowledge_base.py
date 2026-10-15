"""KnowledgeBase 测试：降级模式、mock 向量库注入、后台线程回归（本次事故）。"""
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.knowledge_base import KnowledgeBase  # noqa: E402

MESSAGES = [
    {"role": "user", "content": "我的防火墙开着吗"},
    {"role": "assistant", "content": "防火墙开启中，一切正常"},
]


def _fake_embed(input):
    if isinstance(input, str):
        input = [input]
    return [[0.1] * 8 for _ in input]


# ---- 降级模式：无向量库、无 vLLM ----

def test_degraded_mode(tmp_path):
    kb = KnowledgeBase(persist_dir=tmp_path, vector_db_cfg=None,
                       embedding_cfg={"enabled": False})
    assert kb._store is None
    assert kb._store_ready is False
    assert kb._embed_type == "unavailable"
    assert kb._embed_fn is None

    conv_id = kb.add_conversation(MESSAGES)
    assert conv_id is not None
    assert (tmp_path / "conversations" / f"{conv_id}.md").exists()
    assert kb.conversation_count == 1
    assert kb.count == 0

    hits = kb.search("防火墙")
    assert isinstance(hits, list)
    assert any("防火墙" in h["text"] for h in hits)

    stats = kb.get_stats()
    assert stats["vector_db"] == "none"
    assert "storage_dir" in stats
    assert "chroma_dir" in stats  # 遗留别名


def test_store_present_but_embedding_unavailable_skips_vector_path(tmp_path):
    """向量库可用、嵌入不可用：必须跳过向量路且不崩。

    这是原来靠 `_embed_type != "tfidf-fallback"` 这个字符串比较来把关的组合。
    删掉那个 TF-IDF 兜底类之后改为判断 `_embed_fn is not None`，
    这里把它钉住 —— 否则 `self._embed_fn([...])` 会在 None 上抛 TypeError。
    """
    kb = KnowledgeBase(
        persist_dir=tmp_path,
        vector_db_cfg={"provider": "local", "local": {"path": str(tmp_path / "idx.json")}},
        embedding_cfg={"enabled": False},
    )
    assert kb._store is not None and kb._store.name == "local"
    assert kb._embed_fn is None
    assert kb._store_ready is False

    conv_id = kb.add_conversation(MESSAGES)      # 不得因嵌入缺失而抛错
    assert conv_id is not None
    assert kb.count == 0                          # 没有向量入库
    hits = kb.search("防火墙")                     # 关键词路照常
    assert any("防火墙" in h["text"] for h in hits)

    kb.delete_conversation(conv_id)
    assert not (tmp_path / "conversations" / f"{conv_id}.md").exists()


# ---- 注入 mock 向量库 ----

def _make_mock_store():
    store = MagicMock()
    store.name = "mock"
    store.ping.return_value = True
    store.count.return_value = 3
    store.search.return_value = [
        {"id": "c0", "text": "防火墙开启中", "metadata": {}, "score": 0.9},
    ]
    return store


def _patch_backends(monkeypatch, store):
    # KnowledgeBase 在 __init__ 里 `from .vector_store import create_vector_store`，
    # 运行时从模块取属性，所以 patch vector_store 模块级函数即可生效。
    import agent.vector_store as vsmod
    import agent.knowledge_base as kbmod
    monkeypatch.setattr(vsmod, "create_vector_store", lambda cfg: store)
    monkeypatch.setattr(kbmod, "_create_embedding_fn", lambda cfg: (_fake_embed, "transformers"))


def test_mock_store_add_and_search(tmp_path, monkeypatch):
    store = _make_mock_store()
    _patch_backends(monkeypatch, store)

    kb = KnowledgeBase(persist_dir=tmp_path, vector_db_cfg={"provider": "milvus"})
    assert kb._store_ready is True

    conv_id = kb.add_conversation(MESSAGES)
    assert conv_id is not None
    assert store.add.called
    assert store.ensure_collection.called

    # 向量库里的 chunk id 格式是 f"{conv_id}_{i}"。mock 也按这个格式返回，
    # 否则会被当成与 BM25 命中不同的文档——混合检索是按 id 合并两路的。
    store.search.return_value = [
        {"id": f"{conv_id}_0", "text": "防火墙开启中", "metadata": {}, "score": 0.9},
    ]
    hits = kb.search("防火墙")
    assert store.search.called
    assert hits[0]["text"] == "防火墙开启中"


def test_hybrid_merges_same_chunk_from_both_paths(tmp_path, monkeypatch):
    """两路命中同一分块时应合并成一条（向量路字段更全，以它为准），不能重复出现。"""
    store = _make_mock_store()
    _patch_backends(monkeypatch, store)

    kb = KnowledgeBase(persist_dir=tmp_path, vector_db_cfg={"provider": "milvus"})
    conv_id = kb.add_conversation(MESSAGES)
    store.search.return_value = [
        {"id": f"{conv_id}_0", "text": "来自向量路的文本", "metadata": {}, "score": 0.9},
    ]
    hits = kb.search("防火墙")
    ids = [h["id"] for h in hits]
    assert ids.count(f"{conv_id}_0") == 1
    assert hits[0]["text"] == "来自向量路的文本"


def test_store_search_raises_falls_back(tmp_path, monkeypatch):
    store = _make_mock_store()
    store.search.side_effect = RuntimeError("store down")
    _patch_backends(monkeypatch, store)

    kb = KnowledgeBase(persist_dir=tmp_path, vector_db_cfg={"provider": "milvus"})
    kb.add_conversation(MESSAGES)  # 落一份 Markdown 供关键词搜索
    hits = kb.search("防火墙")
    assert store.search.called
    # 向量路抛异常 → 本次仅用 BM25 关键词路，仍应命中
    assert any("防火墙" in h["text"] for h in hits)


def test_rebuild_index_drops_then_readds(tmp_path, monkeypatch):
    store = _make_mock_store()
    _patch_backends(monkeypatch, store)

    kb = KnowledgeBase(persist_dir=tmp_path, vector_db_cfg={"provider": "milvus"})
    kb.add_conversation(MESSAGES)
    store.add.reset_mock()

    kb.rebuild_index()
    assert store.drop.called
    assert store.add.called


# ---- 后台线程回归（本次事故：ChromaDB 在后台线程段错误）----

def test_kb_usable_from_background_thread(tmp_path):
    kb = KnowledgeBase(persist_dir=tmp_path, vector_db_cfg=None,
                       embedding_cfg={"enabled": False})
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
