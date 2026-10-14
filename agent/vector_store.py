"""Vector Store — Milvus (primary) / Qdrant (fallback).

客户端-服务端向量库：网络客户端天然线程安全，可在后台线程安全调用
（这是替代 ChromaDB 的原因——ChromaDB 1.x 的 Rust 绑定在后台线程调用会段错误）。

设计约束:
  - 模块级不 import 任何第三方 SDK；SDK 在首次真实使用时懒加载。
    缺包时抛 VectorStoreUnavailable，调用方把它当作"不可用"处理，绝不崩溃。
  - 所有网络调用带短超时；服务不可达时 ping() 返回 False，绝不阻塞。
  - create_vector_store 按 provider -> fallback 顺序探测，返回首个可达者。
"""

from __future__ import annotations

import abc
import logging
import uuid
from typing import Any, Optional

logger = logging.getLogger("Guardian.VectorStore")


class VectorStoreUnavailable(Exception):
    """向量库不可用（SDK 缺失或服务不可达）。"""


class VectorStore(abc.ABC):
    """向量库抽象。search 返回与旧 Chroma 一致的 [{id, text, metadata, score}]。"""

    name: str = ""

    @abc.abstractmethod
    def ping(self) -> bool:
        """服务是否可达（短超时探测）。"""

    @abc.abstractmethod
    def ensure_collection(self, name: str, dim: int) -> None:
        """创建集合；已存在且维度不一致时重建（记录警告）。"""

    @abc.abstractmethod
    def count(self) -> int:
        """向量条数（服务不可用时返回 0）。"""

    @abc.abstractmethod
    def add(self, ids: list[str], documents: list[str],
            metadatas: list[dict], vectors: list[list[float]]) -> None:
        """批量写入。ids 为字符串 chunk_id，各后端自行映射到合法主键。"""

    @abc.abstractmethod
    def search(self, query_vector: list[float], top_k: int,
               filter_topics: Optional[list[str]] = None) -> list[dict]:
        """余弦相似度检索，返回 [{id, text, metadata, score}]。"""

    @abc.abstractmethod
    def delete_by_conversation(self, conv_id: str) -> None:
        """按对话 ID 删除该对话的所有向量。"""

    @abc.abstractmethod
    def drop(self) -> None:
        """删除整个集合（重建索引用）。"""


class MilvusStore(VectorStore):
    """Milvus — 通过 pymilvus MilvusClient (gRPC)。"""

    name = "milvus"

    def __init__(self, uri: str, timeout: float = 2.0):
        self._uri = uri
        self._timeout = timeout
        self._client: Any = None
        self._collection_name: Optional[str] = None

    def _client_impl(self) -> Any:
        if self._client is None:
            try:
                from pymilvus import MilvusClient  # noqa: PLC0415
            except ImportError as e:
                raise VectorStoreUnavailable("pymilvus 未安装") from e
            self._client = MilvusClient(uri=self._uri, timeout=self._timeout)
        return self._client

    def ping(self) -> bool:
        try:
            self._client_impl().list_collections()
            return True
        except Exception:
            return False

    def _create(self, name: str, dim: int) -> None:
        from pymilvus import CollectionSchema, DataType, FieldSchema  # noqa: PLC0415

        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=int(dim)),
            FieldSchema(name="conversation_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="role", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="topics", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="timestamp", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
        ]
        schema = CollectionSchema(fields, description="AI Security Guardian conversations")
        index_params = self._client_impl().prepare_index_params()
        index_params.add_index(field_name="vector", index_type="FLAT", metric_type="COSINE")
        self._client_impl().create_collection(
            collection_name=name, schema=schema, index_params=index_params)
        logger.info("Milvus 集合已创建: %s (dim=%s)", name, dim)

    def ensure_collection(self, name: str, dim: int) -> None:
        client = self._client_impl()
        self._collection_name = name
        if not client.has_collection(name):
            self._create(name, dim)
            return
        try:
            desc = client.describe_collection(name)
            vec_field = next(
                (f for f in desc.get("fields", []) if f.get("type") == 101), None)
            existing_dim = vec_field.get("params", {}).get("dim") if vec_field else None
            if existing_dim is not None and int(existing_dim) != int(dim):
                logger.warning("Milvus 维度变化 %s→%s，重建集合 %s", existing_dim, dim, name)
                client.drop_collection(name)
                self._create(name, dim)
        except Exception as e:
            logger.warning("Milvus 维度检查失败(%s)，按原样使用集合 %s", e, name)

    def count(self) -> int:
        if not self._collection_name:
            return 0
        try:
            stats = self._client_impl().get_collection_stats(self._collection_name)
            return int(stats.get("row_count", 0) or 0)
        except Exception:
            return 0

    def add(self, ids: list[str], documents: list[str],
            metadatas: list[dict], vectors: list[list[float]]) -> None:
        rows = []
        for i, cid in enumerate(ids):
            row = {"id": cid, "vector": vectors[i], "text": documents[i]}
            row.update(metadatas[i])
            rows.append(row)
        self._client_impl().insert(collection_name=self._collection_name, data=rows)

    def search(self, query_vector: list[float], top_k: int,
               filter_topics: Optional[list[str]] = None) -> list[dict]:
        filter_expr = ""
        if filter_topics:
            filter_expr = " or ".join(f'topics like "%{t}%"' for t in filter_topics)
        hits = self._client_impl().search(
            collection_name=self._collection_name,
            data=[query_vector],
            limit=top_k,
            filter=filter_expr or None,
            output_fields=["id", "text", "conversation_id", "chunk_index",
                           "role", "topics", "timestamp"],
        )
        results = []
        for hit in (hits[0] if hits else []):
            entity = hit.get("entity", {})
            results.append({
                "id": hit.get("id", ""),
                "text": entity.get("text", ""),
                "metadata": {
                    "conversation_id": entity.get("conversation_id", ""),
                    "chunk_index": entity.get("chunk_index"),
                    "role": entity.get("role", ""),
                    "topics": entity.get("topics", ""),
                },
                "score": hit.get("distance", 0.0),
            })
        return results

    def delete_by_conversation(self, conv_id: str) -> None:
        self._client_impl().delete(
            collection_name=self._collection_name,
            filter=f'conversation_id == "{conv_id}"',
        )

    def drop(self) -> None:
        if self._collection_name and self._client_impl().has_collection(self._collection_name):
            self._client_impl().drop_collection(self._collection_name)


class QdrantStore(VectorStore):
    """Qdrant — 通过 qdrant-client (HTTP)。"""

    name = "qdrant"

    def __init__(self, host: str, port: int, timeout: float = 2.0):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._client: Any = None
        self._collection_name: Optional[str] = None

    def _client_impl(self) -> Any:
        if self._client is None:
            try:
                from qdrant_client import QdrantClient  # noqa: PLC0415
            except ImportError as e:
                raise VectorStoreUnavailable("qdrant-client 未安装") from e
            self._client = QdrantClient(
                url=f"http://{self._host}:{self._port}", timeout=self._timeout)
        return self._client

    def ping(self) -> bool:
        try:
            self._client_impl().get_collections()
            return True
        except Exception:
            return False

    def ensure_collection(self, name: str, dim: int) -> None:
        from qdrant_client.models import Distance, VectorParams  # noqa: PLC0415

        client = self._client_impl()
        self._collection_name = name
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=int(dim), distance=Distance.COSINE),
            )
            logger.info("Qdrant 集合已创建: %s (dim=%s)", name, dim)
            return
        try:
            info = client.get_collection(name)
            vparams = info.config.params.vectors
            existing_dim = (
                next(iter(vparams.values())).size if isinstance(vparams, dict) else vparams.size)
            if int(existing_dim) != int(dim):
                logger.warning("Qdrant 维度变化 %s→%s，重建集合 %s", existing_dim, dim, name)
                client.delete_collection(name)
                client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=int(dim), distance=Distance.COSINE),
                )
        except Exception as e:
            logger.warning("Qdrant 维度检查失败(%s)，按原样使用集合 %s", e, name)

    def count(self) -> int:
        if not self._collection_name:
            return 0
        try:
            return int(self._client_impl().count(self._collection_name).count)
        except Exception:
            return 0

    def add(self, ids: list[str], documents: list[str],
            metadatas: list[dict], vectors: list[list[float]]) -> None:
        from qdrant_client.models import PointStruct  # noqa: PLC0415

        points = []
        for i, cid in enumerate(ids):
            m = metadatas[i]
            topics = [t.strip() for t in str(m.get("topics", "")).split(",") if t.strip()]
            points.append(PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, cid)),
                vector=vectors[i],
                payload={
                    "chunk_id": cid,
                    "text": documents[i],
                    "conversation_id": m.get("conversation_id", ""),
                    "chunk_index": m.get("chunk_index", i),
                    "role": m.get("role", "mixed"),
                    "topics": topics,
                    "timestamp": m.get("timestamp", ""),
                },
            ))
        self._client_impl().upsert(collection_name=self._collection_name, points=points)

    def search(self, query_vector: list[float], top_k: int,
               filter_topics: Optional[list[str]] = None) -> list[dict]:
        from qdrant_client.models import (  # noqa: PLC0415
            FieldCondition,
            Filter,
            MatchAny,
        )

        query_filter = None
        if filter_topics:
            query_filter = Filter(should=[
                FieldCondition(key="topics", match=MatchAny(any=list(filter_topics)))
            ])
        # qdrant-client 从 1.10 起用 query_points 取代了 search，并在后续版本**删除了 search**。
        # pyproject 允许 >=1.9，所以两代都要兼容——否则装上 1.19 就直接
        # "QdrantClient object has no attribute 'search'"，检索静默退回关键词路。
        client = self._client_impl()
        if hasattr(client, "query_points"):
            res = client.query_points(
                collection_name=self._collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            hits = res.points
        else:  # qdrant-client < 1.10
            hits = client.search(
                collection_name=self._collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
            )
        results = []
        for hit in hits:
            payload = hit.payload or {}
            results.append({
                "id": payload.get("chunk_id", str(hit.id)),
                "text": payload.get("text", ""),
                "metadata": {
                    "conversation_id": payload.get("conversation_id", ""),
                    "chunk_index": payload.get("chunk_index"),
                    "role": payload.get("role", ""),
                    "topics": payload.get("topics", ""),
                },
                "score": float(hit.score),
            })
        return results

    def delete_by_conversation(self, conv_id: str) -> None:
        from qdrant_client.models import (  # noqa: PLC0415
            FieldCondition,
            Filter,
            FilterSelector,
            MatchValue,
        )

        self._client_impl().delete(
            collection_name=self._collection_name,
            points_selector=FilterSelector(filter=Filter(
                must=[FieldCondition(key="conversation_id", match=MatchValue(value=conv_id))]
            )),
        )

    def drop(self) -> None:
        if self._collection_name and self._client_impl().collection_exists(self._collection_name):
            self._client_impl().delete_collection(self._collection_name)


def _build_store(name: str, params: dict, timeout: float) -> Optional[VectorStore]:
    """构造 store（仅存连接参数，不触发网络/导入）。"""
    if name == "milvus":
        host = str(params.get("host", "localhost"))
        port = int(params.get("port", 19530))
        return MilvusStore(uri=f"http://{host}:{port}", timeout=timeout)
    if name == "qdrant":
        host = str(params.get("host", "localhost"))
        port = int(params.get("port", 6333))
        return QdrantStore(host=host, port=port, timeout=timeout)
    return None


def create_vector_store(cfg: Optional[dict]) -> Optional[VectorStore]:
    """按 provider -> fallback 顺序探测，返回首个可达的 store；全不可达返回 None。

    cfg 形如 {provider, fallback, timeout, milvus:{...}, qdrant:{...}}。
    """
    if not isinstance(cfg, dict) or not cfg:
        return None
    timeout = float(cfg.get("timeout", 2) or 2)
    for key in ("provider", "fallback"):
        name = cfg.get(key)
        if not name:
            continue
        store = _build_store(str(name), cfg.get(name) or {}, timeout)
        if store is None:
            continue
        try:
            if store.ping():
                logger.info("向量库可用: %s", store.name)
                return store
            logger.debug("向量库 %s 不可达", name)
        except Exception as e:
            logger.debug("向量库 %s 探测失败: %s", name, e)
    return None
