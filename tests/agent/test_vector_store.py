"""VectorStore 探活/降级/缺包测试。不依赖任何真实向量库服务。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.vector_store import (  # noqa: E402
    LocalStore,
    MilvusStore,
    QdrantStore,
    VectorStoreUnavailable,
    create_vector_store,
)

CFG = {
    "provider": "milvus",
    "fallback": "qdrant",
    "timeout": 0.5,
    "milvus": {"host": "localhost", "port": 19530},
    "qdrant": {"host": "localhost", "port": 6333},
}


def test_none_or_empty_config_returns_none():
    assert create_vector_store(None) is None
    assert create_vector_store({}) is None


def test_both_down_returns_none(monkeypatch):
    monkeypatch.setattr(MilvusStore, "ping", lambda self: False)
    monkeypatch.setattr(QdrantStore, "ping", lambda self: False)
    assert create_vector_store(CFG) is None


def test_milvus_available_wins(monkeypatch):
    monkeypatch.setattr(MilvusStore, "ping", lambda self: True)
    monkeypatch.setattr(QdrantStore, "ping", lambda self: False)
    store = create_vector_store(CFG)
    assert store is not None
    assert store.name == "milvus"


def test_milvus_down_qdrant_fallback(monkeypatch):
    monkeypatch.setattr(MilvusStore, "ping", lambda self: False)
    monkeypatch.setattr(QdrantStore, "ping", lambda self: True)
    store = create_vector_store(CFG)
    assert store is not None
    assert store.name == "qdrant"


def test_missing_sdk_does_not_crash(monkeypatch):
    """SDK 缺失时 _client_impl 抛 VectorStoreUnavailable，ping 吞掉 → 返回 None。"""

    def raise_unavail(self):
        raise VectorStoreUnavailable("not installed")

    monkeypatch.setattr(MilvusStore, "_client_impl", raise_unavail)
    monkeypatch.setattr(QdrantStore, "_client_impl", raise_unavail)
    assert create_vector_store(CFG) is None


def test_unknown_provider_skipped():
    cfg = {"provider": "nonexistent", "fallback": "nonexistent2"}
    assert create_vector_store(cfg) is None


# ---------------------------------------------------------------- LocalStore
# 进程内实现：不起任何服务，因此这些用例可以真跑检索（其余用例只能验探活）。

def _store(tmp_path, dim: int = 4) -> LocalStore:
    s = LocalStore(path=str(tmp_path / "idx.json"))
    s.ensure_collection("test", dim)
    return s


def _seed(s: LocalStore) -> None:
    s.add(
        ids=["a", "b", "c"],
        documents=["退票规则", "儿童票年龄", "危险品清单"],
        metadatas=[
            {"conversation_id": "c1", "chunk_index": 0, "role": "user", "topics": "规则,退票"},
            {"conversation_id": "c1", "chunk_index": 1, "role": "user", "topics": "规则,儿童"},
            {"conversation_id": "c2", "chunk_index": 0, "role": "user", "topics": "安全,危险品"},
        ],
        vectors=[[1, 0, 0, 0], [0.9, 0.1, 0, 0], [0, 1, 0, 0]],
    )


def test_local_is_always_reachable_without_any_service():
    """与其他实现的关键差别：ping 恒真，不需要任何外部服务。"""
    cfg = {"provider": "local", "fallback": "milvus", "timeout": 0.5, "local": {}}
    store = create_vector_store(cfg)
    assert store is not None and store.name == "local"


def test_local_provider_takes_precedence_over_fallback(tmp_path):
    """local 恒可达，因此配置里它的顺序决定实际用谁。"""
    cfg = {
        "provider": "local",
        "fallback": "milvus",
        "timeout": 0.5,
        "local": {"path": str(tmp_path / "idx.json")},
    }
    store = create_vector_store(cfg)
    assert store is not None and store.name == "local"


def test_local_cosine_ranking(tmp_path):
    s = _store(tmp_path)
    _seed(s)
    hits = s.search([1, 0, 0, 0], top_k=3)
    assert [h["id"] for h in hits] == ["a", "b", "c"]
    # 归一化后点积 = 余弦：完全相同为 1.0，(0.9,0.1) 为 0.9/√0.82，正交为 0
    assert abs(hits[0]["score"] - 1.0) < 1e-9
    assert abs(hits[1]["score"] - 0.9 / (0.82 ** 0.5)) < 1e-9
    assert abs(hits[2]["score"] - 0.0) < 1e-9


def test_local_filter_topics_matches_milvus_substring_semantics(tmp_path):
    """Milvus 用 `topics like "%t%"`（子串），Local 必须对齐它而不是 Qdrant 的精确匹配。"""
    s = _store(tmp_path)
    _seed(s)
    hits = s.search([1, 0, 0, 0], top_k=3, filter_topics=["危险品"])
    assert [h["id"] for h in hits] == ["c"]
    # 子串：给"退"也应命中 topics 里含"退票"的那条（Milvus 语义下会命中）
    hits = s.search([1, 0, 0, 0], top_k=3, filter_topics=["退"])
    assert [h["id"] for h in hits] == ["a"]


def test_local_upsert_same_id_does_not_duplicate(tmp_path):
    """同一 chunk 重复入库应覆盖而不是堆积——与 Qdrant 的 upsert 一致。"""
    s = _store(tmp_path)
    _seed(s)
    s.add(ids=["a"], documents=["退票规则v2"], metadatas=[{"conversation_id": "c1"}],
          vectors=[[1, 0, 0, 0]])
    assert s.count() == 3
    assert s.search([1, 0, 0, 0], top_k=1)[0]["text"] == "退票规则v2"


def test_local_persists_across_instances(tmp_path):
    s = _store(tmp_path)
    _seed(s)
    again = LocalStore(path=str(tmp_path / "idx.json"))
    assert again.count() == 3
    assert again.search([1, 0, 0, 0], top_k=1)[0]["id"] == "a"


def test_local_delete_by_conversation(tmp_path):
    s = _store(tmp_path)
    _seed(s)
    s.delete_by_conversation("c2")
    assert s.count() == 2
    # c 已被删；a 对查询正交得 0 分，但仍落在 top_k 内——
    # 这与 Milvus 行为一致（按分排序取前 k，不因 0 分剔除）
    assert [h["id"] for h in s.search([0, 1, 0, 0], top_k=3)] == ["b", "a"]


def test_local_dim_change_clears_stale_index(tmp_path):
    """换嵌入模型会改维度；旧向量必须清掉，否则检索会拿不同维度的向量算分。"""
    s = _store(tmp_path, dim=4)
    _seed(s)
    s.ensure_collection("test", 8)
    assert s.count() == 0


def test_local_skips_vectors_with_mismatched_dim(tmp_path):
    """索引里混入不同维度的条目时跳过，不让 zip 静默截断算出一个错的分。"""
    s = _store(tmp_path, dim=4)
    s.ensure_collection("test", 4)
    s.add(ids=["ok"], documents=["四维"], metadatas=[{"conversation_id": "c1"}],
          vectors=[[1, 0, 0, 0]])
    # 直接塞一条 2 维的（模拟索引里残留的旧维度数据）
    s._items.append({"id": "bad", "text": "二维", "vector": [1.0, 0.0],
                     "metadata": {"conversation_id": "c1", "topics": ""}})
    hits = s.search([1, 0, 0, 0], top_k=5)
    assert [h["id"] for h in hits] == ["ok"]


def test_local_drop_empties_index(tmp_path):
    s = _store(tmp_path)
    _seed(s)
    s.drop()
    assert s.count() == 0
