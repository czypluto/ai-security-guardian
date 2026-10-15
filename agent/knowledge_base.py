"""
Knowledge Base — 本地知识库 (RAG)

功能:
  - 对话保存为 Markdown 文件
  - 向量化存储 (Milvus 主 / Qdrant 后备，客户端-服务端)
  - 语义检索历史对话
  - 为 LLM 构建上下文增强提示

嵌入:
  - 本地 WeMM-Embedding-2B，由 scripts/embed_server.py 以 transformers 直载（int8 GPU），
    暴露 OpenAI 兼容的 /v1/embeddings；按需启停见 agent/embed_service.py
  - 嵌入服务不可用时降级为纯 Python TF-IDF 关键词检索

检索:
  - 向量路（Milvus 主 / Qdrant 备）+ 中文 BM25 关键词路，两路 RRF 融合（见 agent/bm25.py）

架构:
  knowledge_base/
  ├── conversations/     # Markdown 对话文件 (始终保留)
  └── vector_meta.json   # 向量库元信息 (集合名/维度/provider)

线程安全: 客户端-服务端 (vLLM/Milvus/Qdrant) 均为网络客户端，可在后台线程安全调用。
ChromaDB 因 Rust 绑定在后台线程段错误而弃用。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .bm25 import Bm25Index, rrf_scores

logger = logging.getLogger("Guardian.KB")

# 内置轻量 Embedding（纯 Python TF-IDF 后备）

class _FallbackEmbedding:
    """轻量级 TF-IDF 向量化，零依赖后备方案。

    用于 vLLM 不可用的场景。虽然不如深度学习模型精准，但对于关键词匹配型检索足够有效。
    """

    def __init__(self):
        self._vocab: Dict[str, int] = {}
        self._idf: Dict[str, float] = {}

    def _tokenize(self, text: str) -> List[str]:
        """中英文混合分词 (字符级 bigram)。"""
        text = text.lower()
        tokens = []
        # 提取中文字符作为独立 token
        chinese = re.findall(r'[一-鿿]+', text)
        for seg in chinese:
            tokens.append(seg)
            # 中文 bigram
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i + 2])
        # 英文/数字单词
        words = re.findall(r'[a-z0-9]{2,}', text)
        tokens.extend(words)
        return tokens

    def fit(self, documents: List[str]):
        """构建 IDF 词汇表。"""
        df: Dict[str, int] = {}
        for doc in documents:
            seen = set(self._tokenize(doc))
            for token in seen:
                df[token] = df.get(token, 0) + 1

        n = len(documents) or 1
        self._vocab = {token: i for i, token in enumerate(sorted(df.keys()))}
        self._idf = {token: __import__('math').log(n / (df[token] + 1)) + 1
                      for token in df}

    def encode(self, text: str, dim: int = 384) -> List[float]:
        """将文本编码为固定维度向量。"""
        tokens = self._tokenize(text)
        if not self._vocab or not tokens:
            return [0.0] * dim

        # TF-IDF 向量
        vec = [0.0] * len(self._vocab)
        for token in tokens:
            if token in self._vocab:
                tf = tokens.count(token) / len(tokens)
                vec[self._vocab[token]] = tf * self._idf.get(token, 1.0)

        # 哈希压缩到目标维度 (feature hashing)
        result = [0.0] * dim
        for i, v in enumerate(vec):
            if v != 0:
                h = hash(f"feat_{i}") % dim
                result[h] += v

        # L2 归一化
        norm = __import__('math').sqrt(sum(x * x for x in result)) or 1.0
        return [x / norm for x in result]


# 本地嵌入（OpenAI 兼容 /v1/embeddings）

class HttpEmbeddingFunction:
    """调用本地嵌入服务（scripts/embed_server.py，WeMM-Embedding-2B）。

    HTTP 契约与 OpenAI /v1/embeddings 一致——所以服务端从 vLLM 换成 transformers
    对这里没有影响，调用方一行都不用改。

    线程安全：纯 HTTP 请求；超时短，服务不可达时快速失败。
    """

    def __init__(self, url: str = "http://localhost:8099",
                 model: str = "WeMM-Embedding-2B", timeout: float = 120.0):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def __call__(self, input):
        # 按需启动：服务不在则拉起并等待就绪（模型加载实测约 20s）
        from .embed_service import get_embed_manager
        mgr = get_embed_manager(url=self.url)
        if not mgr.ensure_running():
            raise RuntimeError("嵌入服务未就绪，本次嵌入跳过")

        if isinstance(input, str):
            input = [input]
        resp = requests.post(
            f"{self.url}/v1/embeddings",
            json={"model": self.model, "input": list(input)},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items]

    # 与旧 OllamaEmbeddingFunction 相同的兼容接口
    def embed_query(self, input):
        return self(input)

    def embed_documents(self, input):
        return self(input)

    def name(self) -> str:
        return f"local-{self.model}"

    def get_config(self):
        return {"url": self.url, "model": self.model, "timeout": self.timeout}


# Embedding 工厂

def _create_embedding_fn(embedding_cfg: Optional[dict] = None):
    """创建 embedding 函数：优先本地嵌入服务，不可用时降级 TF-IDF。"""
    cfg = embedding_cfg if isinstance(embedding_cfg, dict) else {}
    if cfg.get("enabled", True):
        try:
            url = cfg.get("url", "http://localhost:8099")
            model = cfg.get("model", "WeMM-Embedding-2B")
            timeout = float(cfg.get("timeout", 120))
            fn = HttpEmbeddingFunction(url=url, model=model, timeout=timeout)
            # 真实探测一次：服务没起会走按需拉起，首次需等模型加载（~20s）
            dim = len(fn(["dim-probe"])[0])
            logger.info("Embedding: 本地嵌入服务 (%s, dim=%s)", model, dim)
            return fn, "transformers"
        except Exception as e:
            logger.warning("本地嵌入服务不可用(%s)，降级 TF-IDF 关键词检索", e)
    else:
        logger.warning("未启用本地嵌入，降级 TF-IDF 关键词检索")

    return _FallbackEmbedding(), "tfidf-fallback"


# 对话 Markdown 存储

class ConversationStore:
    """将对话保存为结构化 Markdown 文件。"""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, messages: List[Dict[str, str]],
             metadata: Dict[str, Any] = None) -> Path:
        """保存对话为 Markdown 文件。

        参数:
          messages: [{"role": "user/assistant/system", "content": "..."}]
          metadata: 额外元数据 (timestamp, topics, etc.)

        返回: 文件路径
        """
        if not messages:
            return None

        now = datetime.now()
        timestamp = metadata.get("timestamp", now.isoformat()) if metadata else now.isoformat()
        filename = now.strftime("%Y-%m-%d_%H%M%S") + ".md"
        filepath = self.base_dir / filename

        # 提取话题关键词
        topics = self._extract_topics(messages)
        msg_count = sum(1 for m in messages if m.get("role") in ("user", "assistant"))

        # 构建 Markdown
        lines = [
            "---",
            f"timestamp: {timestamp}",
            f"message_count: {msg_count}",
            f"topics: {json.dumps(topics, ensure_ascii=False)}",
        ]
        if metadata:
            for k, v in metadata.items():
                if k not in ("timestamp", "message_count", "topics"):
                    lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        lines.append("---")
        lines.append("")
        lines.append("# AI Security Guardian — 对话记录")
        lines.append(f"**时间**: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**消息数**: {msg_count} 轮对话")
        if topics:
            lines.append(f"**话题**: {', '.join(topics)}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 逐条消息
        q_idx = 0
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "").strip()
            if not content:
                continue

            if role in ("user", "human"):
                q_idx += 1
                lines.append(f"## Q{q_idx}: {content[:80]}{'...' if len(content) > 80 else ''}")
                lines.append("**User**:")
                lines.append(content)
                lines.append("")
            elif role in ("ai", "assistant", "bot", "model"):
                lines.append("**安小盾**:")
                lines.append(content)
                lines.append("")
            elif role == "system":
                lines.append(f"**System**: {content}")
                lines.append("")

        text = "\n".join(lines)
        filepath.write_text(text, encoding="utf-8")
        logger.info(f"对话已保存: {filepath.name} ({msg_count} 轮)")

        return filepath

    def _extract_topics(self, messages: List[Dict[str, str]]) -> List[str]:
        """从对话中提取关键词话题。"""
        # 安全领域关键词
        SECURITY_KEYWORDS = {
            "防火墙": "防火墙", "firewall": "防火墙",
            "端口": "端口扫描", "port": "端口扫描",
            "病毒": "病毒检测", "virus": "病毒检测", "malware": "病毒检测",
            "进程": "进程监控", "process": "进程监控",
            "漏洞": "漏洞扫描", "vuln": "漏洞扫描",
            "扫描": "安全扫描", "scan": "安全扫描",
            "网络": "网络监控", "network": "网络监控",
            "威胁": "威胁分析", "threat": "威胁分析",
            "CPU": "系统资源", "内存": "系统资源", "memory": "系统资源",
            "Defender": "杀毒软件", "defender": "杀毒软件",
            "IP": "IP分析", "连接": "网络连接",
            "密码": "密码安全", "password": "密码安全",
            "更新": "系统更新", "update": "系统更新",
            "日志": "日志分析", "log": "日志分析",
            "攻击": "攻击检测", "attack": "攻击检测",
        }

        full_text = " ".join(m.get("content", "") for m in messages).lower()
        found = set()
        for keyword, topic in SECURITY_KEYWORDS.items():
            if keyword.lower() in full_text:
                found.add(topic)

        return sorted(found)[:8]  # 最多 8 个话题

    def list_files(self) -> List[Path]:
        """列出所有已保存的对话文件。"""
        return sorted(self.base_dir.glob("*.md"), reverse=True)

    def load(self, filepath: Path) -> str:
        """读取对话文件内容。"""
        return filepath.read_text(encoding="utf-8")


# 知识库

class KnowledgeBase:
    """本地知识库 — 语义检索历史对话。

    向量存于可插拔的 VectorStore（默认**进程内**，可选 Milvus/Qdrant）；
    Markdown 始终存于本地，是事实源。
    向量库不可用时自动降级为关键词检索，绝不阻塞/崩溃。
    """

    def __init__(
        self,
        persist_dir: str = None,
        embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2",
        collection_name: str = "security_conversations",
        vector_db_cfg: Optional[dict] = None,
        embedding_cfg: Optional[dict] = None,
    ):
        """参数:
          persist_dir: 持久化目录，默认项目根目录下的 knowledge_base/
          embedding_model: 遗留参数（嵌入由 embedding_cfg 驱动），保留以兼容旧调用
          collection_name: 向量集合名
          vector_db_cfg: 向量库配置 {provider, fallback, timeout, milvus, qdrant}
          embedding_cfg: 嵌入配置 {url, model, timeout, enabled}
        """
        if persist_dir is None:
            persist_dir = Path(__file__).parent.parent / "knowledge_base"
        self.persist_dir = Path(persist_dir)
        self.conversations_dir = self.persist_dir / "conversations"
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)

        # Conversation store (Markdown，永远可用)
        self.store = ConversationStore(self.conversations_dir)

        # Embedding（优先本地嵌入服务；不可用时降级）
        self._embed_fn, self._embed_type = _create_embedding_fn(embedding_cfg)

        # 向量库（默认进程内；可选 Milvus/Qdrant；全不可用时为 None）
        from .vector_store import create_vector_store
        self._store = create_vector_store(vector_db_cfg)
        self._store_ready = (self._store is not None
                             and self._embed_type != "tfidf-fallback")
        self._vector_db_name = self._store.name if self._store else None
        self._dim: Optional[int] = None
        self._collection_name = collection_name

        # 中文 BM25（关键词路）— 懒加载；语料变动时置 None 触发重建
        self._bm25: Optional[Bm25Index] = None
        self._bm25_chunks: Dict[str, Dict[str, Any]] = {}

        # 集合初始化（维度探测 + 建/校验集合）；失败则降级，不阻塞
        if self._store_ready:
            try:
                self._ensure_collection()
            except Exception as e:
                logger.warning("向量集合初始化失败(%s)，降级关键词检索", e)
                self._store = None
                self._store_ready = False

    # 向量集合

    def _ensure_collection(self):
        """探测嵌入维度并确保集合存在（维度不一致时重建）。"""
        if not self._store_ready:
            return
        vec = self._embed_fn(["dim-probe"])[0]
        self._dim = int(len(vec))
        self._store.ensure_collection(self._collection_name, self._dim)
        self._write_vector_meta()

    def _write_vector_meta(self):
        meta = {
            "collection_name": self._collection_name,
            "dim": self._dim,
            "provider": self._vector_db_name,
            "embedding_type": self._embed_type,
        }
        try:
            (self.persist_dir / "vector_meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # 写入

    def add_conversation(self, messages: List[Dict[str, str]],
                         metadata: Dict[str, Any] = None) -> Optional[str]:
        """添加对话到知识库。

        1. 保存为 Markdown 文件（始终执行，向量库不可用也不影响）
        2. 按 Q&A 分块
        3. 向量化存储到 Milvus/Qdrant

        返回: 对话 ID (文件路径 stem)
        """
        # 1. 保存 Markdown
        md_path = self.store.save(messages, metadata)
        if md_path is None:
            return None

        conv_id = md_path.stem

        # 2. 分块 — 每个 Q&A 对作为一个文档
        chunks = self._chunk_conversation(messages, conv_id)

        # 3. 向量化存储（失败仅记日志，不影响 Markdown）
        self._vectorize_chunks(conv_id, chunks, metadata or {})

        self._bm25 = None  # 语料已变，关键词索引下轮懒重建
        return conv_id

    def _vectorize_chunks(self, conv_id: str, chunks: List[Dict[str, Any]],
                          metadata: Dict[str, Any]):
        """分块嵌入并写入向量库（吞掉异常，保证 add_conversation 永不因向量失败崩溃）。"""
        if not self._store_ready or not chunks:
            return
        ids = [f"{conv_id}_{i}" for i in range(len(chunks))]
        documents = [c["text"] for c in chunks]
        metadatas = [{
            "conversation_id": conv_id,
            "timestamp": metadata.get("timestamp", ""),
            "topics": ", ".join(c.get("topics", [])),
            "chunk_index": i,
            "role": c.get("role", "mixed"),
        } for i, c in enumerate(chunks)]
        try:
            vectors = self._embed_fn(documents)
            self._store.add(ids=ids, documents=documents,
                            metadatas=metadatas, vectors=vectors)
            logger.info("知识库已索引: %s (%s 个分块)", conv_id, len(chunks))
        except Exception as e:
            logger.error("向量写入失败: %s", e)

    def _chunk_conversation(self, messages: List[Dict[str, str]],
                            conv_id: str) -> List[Dict[str, Any]]:
        """将对话切分为 Q&A 分块。"""
        chunks = []
        current_q = None
        current_a_parts = []

        def flush():
            nonlocal current_q, current_a_parts
            if current_q:
                q_text = current_q.get("content", "")
                a_text = "\n".join(current_a_parts) if current_a_parts else "(无回答)"
                combined = f"Q: {q_text}\nA: {a_text}"
                chunks.append({
                    "text": combined[:2000],  # 限制长度
                    "topics": self.store._extract_topics([current_q]),
                    "role": "qa_pair",
                })
            current_q = None
            current_a_parts = []

        for msg in messages:
            role = msg.get("role", "")
            if role in ("user", "human"):
                flush()
                current_q = msg
            elif role in ("ai", "assistant", "bot", "model"):
                if current_q:
                    current_a_parts.append(msg.get("content", ""))
                else:
                    # 独立 AI 消息
                    chunks.append({
                        "text": f"A: {msg.get('content', '')[:2000]}",
                        "topics": [],
                        "role": "ai_standalone",
                    })
        # system/tool 消息跳过，不参与分块

        flush()
        return chunks

    # 检索

    # 关键词路（中文 BM25）

    def _ensure_bm25_index(self) -> Bm25Index:
        """懒加载**分块级** BM25 索引。

        语料取自 Markdown（事实源），切块方式与向量化完全一致，因此 doc_id 就是
        向量库里的 chunk id（``{conv_id}_{i}``）——**两路的键必须一致，RRF 才能对齐融合**。
        语料变动（新增/删除对话、重建索引）时把 ``self._bm25`` 置 None 即触发重建。
        """
        if self._bm25 is not None:
            return self._bm25
        chunks: Dict[str, Dict[str, Any]] = {}
        for md_file in self.store.list_files():
            try:
                messages = self._parse_markdown_to_messages(self.store.load(md_file))
                if not messages:
                    continue
                for i, chunk in enumerate(self._chunk_conversation(messages, md_file.stem)):
                    chunks[f"{md_file.stem}_{i}"] = {
                        "text": chunk["text"],
                        "topics": chunk.get("topics") or [],
                        "role": chunk.get("role", ""),
                        "conversation_id": md_file.stem,
                        "chunk_index": i,
                        "source": md_file.name,
                    }
            except Exception as e:  # noqa: BLE001
                logger.debug("BM25 索引跳过 %s: %s", md_file.name, e)
        self._bm25_chunks = chunks
        self._bm25 = Bm25Index().build({cid: c["text"] for cid, c in chunks.items()})
        logger.info("BM25 索引就绪: %d 个分块", len(chunks))
        return self._bm25

    def _bm25_search(self, query: str, top_k: int,
                     filter_topics: List[str] = None) -> List[Dict[str, Any]]:
        """关键词路召回，返回结构与向量路保持一致。"""
        index = self._ensure_bm25_index()
        allow = None
        if filter_topics:
            # 与向量路的 topics 过滤口径一致
            allow = [cid for cid, c in self._bm25_chunks.items()
                     if any(t in ", ".join(c.get("topics") or []) for t in filter_topics)]
        out: List[Dict[str, Any]] = []
        for cid, score in index.search(query, top_k=top_k, allow=allow):
            c = self._bm25_chunks[cid]
            out.append({
                "id": cid,
                "text": c["text"],
                "metadata": {
                    "conversation_id": c["conversation_id"],
                    "chunk_index": c["chunk_index"],
                    "role": c["role"],
                    "topics": ", ".join(c.get("topics") or []),
                    "source": c["source"],
                },
                "score": score,
            })
        return out

    # 检索

    def search(self, query: str, top_k: int = 5,
               filter_topics: List[str] = None) -> List[Dict[str, Any]]:
        """混合检索：向量路 + 中文 BM25 路，**RRF 融合**。

        相比原来「向量可用就不看关键词、挂了才退到整篇词频扫描」的单选式检索：
        - 两路**并行召回再融合**，向量补语义、BM25 补精确术语；
        - 向量库不可用时自动退为「仅 BM25」，仍远强于整篇词频扫描；
        - 两路都无结果才退到兜底实现。

        返回: [{id, text, metadata, score}, ...]；融合后 score 为 RRF 分。
        """
        vec_hits: List[Dict[str, Any]] = []
        if self._store_ready and self.count:
            try:
                qv = self._embed_fn([query])[0]
                vec_hits = self._store.search(qv, min(top_k, self.count), filter_topics)
            except Exception as e:  # noqa: BLE001
                logger.warning("向量检索失败(%s)，本次仅用关键词路", e)

        try:
            kw_hits = self._bm25_search(query, top_k=max(top_k * 2, 8),
                                        filter_topics=filter_topics)
        except Exception as e:  # noqa: BLE001
            logger.warning("BM25 检索失败(%s)，本次仅用向量路", e)
            kw_hits = []

        if not vec_hits and not kw_hits:
            return self._fallback_search(query, top_k)

        # 同一分块可能两路都命中：保留字段更全的一条（向量路来自库，元数据更完整）
        by_id: Dict[str, Dict[str, Any]] = {h["id"]: h for h in kw_hits}
        by_id.update({h["id"]: h for h in vec_hits})
        scores = rrf_scores([[h["id"] for h in vec_hits], [h["id"] for h in kw_hits]])
        order = sorted(scores, key=lambda d: (-scores[d], d))
        fused: List[Dict[str, Any]] = []
        for cid in order[:top_k]:
            hit = by_id.get(cid)
            if hit:
                # 对外给 RRF 分（两路量纲不同，直接暴露来源分会让调用方误比较）
                fused.append({**hit, "score": round(scores[cid], 6)})
        return fused

    def _fallback_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """关键词搜索后备方案 — 扫描 Markdown 文件。"""
        results = []
        query_lower = query.lower()
        query_terms = re.findall(r'[一-鿿]+|[a-z0-9]{2,}', query_lower)

        for md_file in self.store.list_files():
            try:
                content = self.store.load(md_file)
                content_lower = content.lower()

                # 计算关键词匹配分数
                score = 0
                for term in query_terms:
                    score += content_lower.count(term)

                # 标题匹配加分
                if any(term in md_file.stem.lower() for term in query_terms):
                    score += 5

                if score > 0:
                    # 提取相关片段
                    lines = content.split("\n")
                    best_line_idx = 0
                    best_line_score = 0
                    for i, line in enumerate(lines):
                        ls = sum(line.lower().count(t) for t in query_terms)
                        if ls > best_line_score:
                            best_line_score = ls
                            best_line_idx = i

                    # 取上下文片段
                    start = max(0, best_line_idx - 3)
                    end = min(len(lines), best_line_idx + 5)
                    snippet = "\n".join(lines[start:end])

                    results.append({
                        "id": md_file.stem,
                        "text": snippet[:1000],
                        "metadata": {"source": md_file.name},
                        "score": score,
                    })
            except Exception:
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    # 上下文构建

    def build_context(self, query: str, top_k: int = 3,
                      max_tokens: int = 800) -> str:
        """为 LLM 构建知识库上下文。

        检索相关历史对话，格式化为可用于 prompt 的文本。
        """
        results = self.search(query, top_k=top_k)

        if not results:
            return ""

        lines = [
            "## 相关知识库记录",
            "以下是从历史对话中检索到的相关信息，可参考用于回答:",
            "",
        ]

        for i, r in enumerate(results, 1):
            text = r["text"]
            meta = r.get("metadata", {})
            topics = meta.get("topics", "")

            header = f"### 参考 {i}"
            if topics:
                header += f" [{topics}]"
            lines.append(header)
            lines.append(text[:400])  # 限制每条长度
            lines.append("")

        context = "\n".join(lines)

        # Token 预算控制 (粗略: 1 token ≈ 2 中文字符 ≈ 4 英文字符)
        if len(context) > max_tokens * 2:
            context = context[:max_tokens * 2] + "\n..."

        return context

    # 管理

    @property
    def count(self) -> int:
        """向量库文档总数（不可用/异常时为 0）。"""
        if not self._store_ready:
            return 0
        try:
            return self._store.count()
        except Exception:
            return 0

    @property
    def conversation_count(self) -> int:
        """已保存对话文件数。"""
        return len(self.store.list_files())

    def delete_conversation(self, conv_id: str):
        """删除对话及其向量。"""
        if self._store_ready:
            try:
                self._store.delete_by_conversation(conv_id)
            except Exception as e:
                logger.warning("删除向量失败: %s", e)

        # 删除 Markdown 文件
        md_path = self.conversations_dir / f"{conv_id}.md"
        if md_path.exists():
            md_path.unlink()
            logger.info(f"已删除对话: {conv_id}")

        self._bm25 = None  # 语料已变，关键词索引下轮懒重建

    def rebuild_index(self):
        """从 Markdown 文件重建整个向量索引。"""
        if not self._store_ready:
            logger.warning("向量库不可用，无法重建索引")
            return

        # 清空并重建集合
        try:
            self._store.drop()
            self._ensure_collection()
        except Exception as e:
            logger.warning("重建集合失败: %s", e)
            self._store_ready = False
            return

        # 重新索引所有对话（只向量化，不重写 Markdown）
        for md_file in self.store.list_files():
            try:
                content = self.store.load(md_file)
                messages = self._parse_markdown_to_messages(content)
                if messages:
                    chunks = self._chunk_conversation(messages, md_file.stem)
                    self._vectorize_chunks(md_file.stem, chunks, {})
            except Exception as e:
                logger.warning(f"重新索引 {md_file.name} 失败: {e}")

        self._bm25 = None  # 关键词索引随之重建
        logger.info(f"索引重建完成: {self.count} 条记录")

    def _parse_markdown_to_messages(self, content: str) -> List[Dict[str, str]]:
        """将保存的 Markdown 解析回消息列表。"""
        messages = []
        lines = content.split("\n")
        current_role = None
        current_content = []
        in_frontmatter = False
        frontmatter_seen = False

        for line in lines:
            stripped = line.strip()
            if not frontmatter_seen:
                # 仅文件头部的 --- 是 frontmatter 边界；关闭后其余 --- 只是正文分隔线
                if stripped == "---":
                    in_frontmatter = not in_frontmatter
                    if not in_frontmatter:
                        frontmatter_seen = True
                    continue
                if in_frontmatter:
                    continue
            else:
                if stripped == "---" or not stripped:
                    continue  # 正文分隔线/空行

            if line.startswith("## ") or line.startswith("# "):
                continue  # 跳过标题

            if line.startswith("**User**:"):
                if current_role and current_content:
                    messages.append({"role": current_role,
                                     "content": "\n".join(current_content).strip()})
                current_role = "user"
                current_content = []
            elif line.startswith("**安小盾**:"):
                if current_role and current_content:
                    messages.append({"role": current_role,
                                     "content": "\n".join(current_content).strip()})
                current_role = "assistant"
                current_content = []
            elif line.startswith("**System**:"):
                if current_role and current_content:
                    messages.append({"role": current_role,
                                     "content": "\n".join(current_content).strip()})
                current_role = "system"
                current_content = [line.replace("**System**:", "").strip()]
            else:
                if current_role:
                    current_content.append(line)

        if current_role and current_content:
            messages.append({"role": current_role,
                             "content": "\n".join(current_content).strip()})

        return messages

    def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息。"""
        return {
            "conversations": self.conversation_count,
            "vector_count": self.count,
            "bm25_chunks": len(self._ensure_bm25_index()) if self.conversation_count else 0,
            "embedding_type": self._embed_type,
            "vector_db": self._vector_db_name or "none",
            "storage_dir": str(self.conversations_dir),
            "conversations_dir": str(self.conversations_dir),
            "chroma_dir": str(self.conversations_dir),  # 遗留别名
        }


# 全局单例

_kb_instance: Optional[KnowledgeBase] = None
_kb_lock = threading.Lock()


def get_knowledge_base(persist_dir: str = None,
                       vector_db_cfg: Optional[dict] = None,
                       embedding_cfg: Optional[dict] = None) -> KnowledgeBase:
    """获取全局知识库实例 (懒加载单例，线程安全)。"""
    global _kb_instance
    if _kb_instance is None:
        with _kb_lock:
            if _kb_instance is None:
                _kb_instance = KnowledgeBase(
                    persist_dir=persist_dir,
                    vector_db_cfg=vector_db_cfg,
                    embedding_cfg=embedding_cfg,
                )
    return _kb_instance


def reset_knowledge_base():
    """重置知识库实例 (用于测试)。"""
    global _kb_instance
    _kb_instance = None
