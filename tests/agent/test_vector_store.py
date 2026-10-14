"""VectorStore 探活/降级/缺包测试。不依赖任何真实向量库服务。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.vector_store import (  # noqa: E402
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
