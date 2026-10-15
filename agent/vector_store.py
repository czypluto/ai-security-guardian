"""Vector Store — Local (默认) / Milvus / Qdrant。

三个实现，按**是否要常驻服务**分两类：

  LocalStore   进程内，纯 Python 暴力余弦，零第三方依赖 —— **本地单用户默认用它**
  Milvus/Qdrant 客户端-服务端，需要另起容器；留给"语料涨到暴力检索扛不住"之后

为什么默认是本地的：见 `LocalStore` 的 docstring —— 简言之，为几十条对话向量的
检索常驻一个容器不划算，而那条路径会拉进 chromadb / transformers / scipy 等一串重依赖。

（客户端-服务端曾替代 ChromaDB，因为 ChromaDB 1.x 的 Rust 绑定在后台线程调用会段错误。

设计约束:
  - 模块级不 import 任何第三方 SDK；SDK 在首次真实使用时懒加载。
    缺包时抛 VectorStoreUnavailable，调用方把它当作"不可用"处理，绝不崩溃。
  - 网络调用带短超时；服务不可达时 ping() 返回 False，绝不阻塞。
  - create_vector_store 按 provider -> fallback 顺序探测，返回首个可达者。
"""

from __future__ import annotations

import abc
import json
import logging
import math
import os
import uuid
from pathlib import Path
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


# 默认落盘位置：紧挨着它索引的语料（knowledge_base/），便于找到与删除
_DEFAULT_LOCAL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "knowledge_base", ".vector_index.json")


def _l2(v: list[float]) -> list[float]:
    """L2 归一化。零向量返回原样（余弦相似度对零向量无定义，返回 0 分更诚实）。"""
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else list(v)


class LocalStore(VectorStore):
    """进程内向量库：纯 Python 暴力余弦 + JSON 落盘。**零第三方依赖**。

    ## 为什么加它

    Milvus / Qdrant 都是**客户端-服务端**，为了几十条对话向量的检索要常驻一个容器。
    而这是个**本地单用户 agent**，自身还做文件完整性校验、刻意压制第三方依赖 ——
    实测 venv 里 145 个包中，`chromadb / qdrant-client / transformers / scipy /
    pandas / onnxruntime` 这些重依赖**全部只为向量库这条路径存在**。

    语料分块后只有几十条（8 篇 md / 16K 字符，按 Q&A 分块），
    纯 Python 暴力检索约 3–8 ms。**这个量级上暴力不是妥协，是正解** ——
    它把一整条重依赖链连同"容器起没起"这个运维问题一起去掉了。

    ## 为什么不用 numpy

    numpy 恰恰是被上面那些重依赖拉进来的。用它等于把要摆脱的东西请回来。

    ## 规模边界

    暴力检索是 O(条目数 × 维度)。实测纯 Python 下约 2000–5000 条以内都在
    100 ms 内；再往上应换 ANN 索引（那时也该换回真正的向量库了）。

    ## 语义与 MilvusStore 对齐（配置里的主 provider）

    - COSINE：写入时即 L2 归一化，检索退化为点积（省掉每次查询重算模长）
    - `filter_topics`：**子串匹配**，等价 Milvus 的 `topics like "%t%"`
      （注意 QdrantStore 用的是 `MatchAny` 精确匹配 —— 两个后端本来就不一致，
      这里对齐主用的 Milvus）
    - 返回 `[{id, text, metadata, score}]`，score 为余弦相似度，越大越相似
    """

    name = "local"

    def __init__(self, path: str, timeout: float = 2.0):
        self._path = Path(path)
        self._timeout = timeout
        self._collection_name: Optional[str] = None
        self._dim: Optional[int] = None
        self._items: list[dict] = []
        self._loaded = False

    # ---- 持久化（原子写，避免写到一半留下半截 JSON）----

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.is_file():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._dim = raw.get("dim")
                self._items = raw.get("items") or []
                logger.info("本地向量库已载入: %s（%d 条, dim=%s）",
                            self._path.name, len(self._items), self._dim)
        except Exception as e:  # noqa: BLE001
            logger.warning("本地向量库载入失败(%s)，按空索引继续", e)
            self._items = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(
                json.dumps({"dim": self._dim, "items": self._items}, ensure_ascii=False),
                encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception as e:  # noqa: BLE001
            logger.warning("本地向量库落盘失败(不影响检索): %s", e)

    # ---- VectorStore 接口 ----

    def ping(self) -> bool:
        self._load()
        return True        # 进程内，没有"不可达"这回事

    def ensure_collection(self, name: str, dim: int) -> None:
        self._load()
        self._collection_name = name
        if self._dim is not None and int(self._dim) != int(dim) and self._items:
            logger.warning("本地向量库维度变化 %s→%s，清空索引（下次入库会重建）",
                           self._dim, dim)
            self._items = []
        self._dim = int(dim)
        self._save()

    def count(self) -> int:
        self._load()
        return len(self._items)

    def add(self, ids: list[str], documents: list[str],
            metadatas: list[dict], vectors: list[list[float]]) -> None:
        """按 id 覆盖写入（upsert）—— 与 Qdrant 一致，重复入库不会产生重复条目。"""
        self._load()
        if vectors and self._dim is None:
            self._dim = len(vectors[0])
        by_id = {it["id"]: it for it in self._items}
        for i, cid in enumerate(ids):
            m = metadatas[i] or {}
            by_id[cid] = {
                "id": cid,
                "text": documents[i],
                "metadata": {
                    "conversation_id": m.get("conversation_id", ""),
                    "chunk_index": m.get("chunk_index"),
                    "role": m.get("role", ""),
                    "topics": m.get("topics", ""),
                },
                # 写入时归一化：检索时只需点积，省掉每次查询重算所有模长
                "vector": _l2([float(x) for x in vectors[i]]),
            }
        self._items = list(by_id.values())
        self._save()

    def search(self, query_vector: list[float], top_k: int,
               filter_topics: Optional[list[str]] = None) -> list[dict]:
        self._load()
        if not self._items or not query_vector:
            return []
        q = _l2([float(x) for x in query_vector])
        scored: list[tuple[float, dict]] = []
        for it in self._items:
            topics = str(it["metadata"].get("topics") or "")
            if filter_topics and not any(t in topics for t in filter_topics):
                continue
            v = it["vector"]
            # 维度不一致（例如换过嵌入模型且索引没重建）时跳过，不让 zip 悄悄截断
            if len(v) != len(q):
                continue
            scored.append((sum(a * b for a, b in zip(q, v)), it))
        scored.sort(key=lambda kv: -kv[0])
        return [{
            "id": it["id"],
            "text": it["text"],
            "metadata": dict(it["metadata"]),
            "score": float(s),
        } for s, it in scored[:top_k]]

    def delete_by_conversation(self, conv_id: str) -> None:
        self._load()
        before = len(self._items)
        self._items = [it for it in self._items
                       if str(it["metadata"].get("conversation_id") or "") != conv_id]
        if len(self._items) != before:
            self._save()

    def drop(self) -> None:
        self._load()
        self._items = []
        self._save()


def _build_store(name: str, params: dict, timeout: float) -> Optional[VectorStore]:
    """构造 store（仅存连接参数，不触发网络/导入）。"""
    if name == "local":
        return LocalStore(path=str(params.get("path") or _DEFAULT_LOCAL_PATH),
                          timeout=timeout)
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
