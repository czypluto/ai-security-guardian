"""
============================================================
 Knowledge Base — 本地向量知识库
 Local Vector Knowledge Base for AI Security Guardian

 功能:
   - 对话保存为 Markdown 文件
   - 向量化存储 (ChromaDB + 本地 Embedding)
   - 语义检索历史对话
   - 为 LLM 构建上下文增强提示

 架构:
   knowledge_base/
   ├── conversations/     # Markdown 对话文件
   └── chroma/            # ChromaDB 向量数据库

 依赖:
   pip install chromadb sentence-transformers
============================================================
"""
from __future__ import annotations

import os
import re
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("Guardian.KB")

# 加载 .env 环境变量 (用于 HF_ENDPOINT 等)
def _load_dotenv():
    import os as _os
    env_path = _os.path.join(_os.path.dirname(__file__), "..", ".env")
    env_path = _os.path.normpath(env_path)
    if not _os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key not in _os.environ:
                _os.environ[key] = val

_load_dotenv()


# ============================================================
# 内置轻量 Embedding — 纯 Python TF-IDF 后备
# 当 sentence-transformers 不可用时自动降级
# ============================================================

class _FallbackEmbedding:
    """轻量级 TF-IDF 向量化，零依赖后备方案。

    用于 sentence-transformers 未安装的场景。
    虽然不如深度学习模型精准，但对于关键词匹配型检索足够有效。
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


# ============================================================
# Embedding 工厂
# ============================================================

def _create_embedding_fn(model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
    """创建 embedding 函数，自动降级。

    优先级:
      1. SentenceTransformers (多语言，需 torch)
      2. ONNX Runtime (all-MiniLM-L6-v2，无需 CUDA DLL)
      3. 纯 Python TF-IDF (零依赖兜底)
    """
    # L1: SentenceTransformers (多语言效果最好，但依赖 torch)
    try:
        from chromadb.utils import embedding_functions
        fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name,
            device="cpu",
        )
        logger.info(f"Embedding: sentence-transformers ({model_name})")
        try:
            _ = fn(["test"])
        except Exception:
            pass
        return fn, "sentence-transformers"
    except Exception as e:
        logger.debug(f"SentenceTransformer 不可用: {e}")

    # L2: ONNX Runtime (无需 CUDA DLL，无需 torch)
    try:
        from chromadb.utils import embedding_functions
        fn = embedding_functions.ONNXMiniLM_L6_V2()
        logger.info("Embedding: ONNX (all-MiniLM-L6-v2)")
        try:
            _ = fn(["test"])
        except Exception:
            pass
        return fn, "onnx"
    except Exception as e:
        logger.debug(f"ONNX 不可用: {e}")

    # L3: TF-IDF 纯 Python 兜底
    logger.warning("所有 Embedding 后端不可用，降级为 TF-IDF 关键词匹配")
    fallback = _FallbackEmbedding()
    return fallback, "tfidf-fallback"


# ============================================================
# 对话 Markdown 存储
# ============================================================

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
                lines.append(f"**User**:")
                lines.append(content)
                lines.append("")
            elif role in ("ai", "assistant", "bot", "model"):
                lines.append(f"**安小盾**:")
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


# ============================================================
# 向量知识库
# ============================================================

class KnowledgeBase:
    """本地向量知识库 — 语义检索历史对话。

    使用方式:
      kb = KnowledgeBase(persist_dir="./knowledge_base")
      kb.add_conversation(messages, metadata={"topic": "firewall"})
      results = kb.search("防火墙状态怎么样", top_k=5)
      context = kb.build_context("防火墙状态怎么样")
    """

    def __init__(
        self,
        persist_dir: str = None,
        embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2",
        collection_name: str = "security_conversations",
    ):
        """
        参数:
          persist_dir: 持久化目录，默认项目根目录下的 knowledge_base/
          embedding_model: sentence-transformers 模型名
          collection_name: ChromaDB 集合名
        """
        # 确定持久化目录
        if persist_dir is None:
            persist_dir = Path(__file__).parent.parent / "knowledge_base"
        self.persist_dir = Path(persist_dir)
        self.chroma_dir = self.persist_dir / "chroma"
        self.conversations_dir = self.persist_dir / "conversations"
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)

        # Conversation store
        self.store = ConversationStore(self.conversations_dir)

        # Embedding
        self._embed_fn, self._embed_type = _create_embedding_fn(embedding_model)

        # ChromaDB
        self._collection = None
        self._collection_name = collection_name
        self._init_chroma()

    def _init_chroma(self):
        """初始化 ChromaDB 客户端和集合。"""
        try:
            import chromadb
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=str(self.chroma_dir),
                settings=Settings(anonymized_telemetry=False),
            )

            # 获取或创建集合
            try:
                self._collection = self._client.get_collection(
                    name=self._collection_name,
                    embedding_function=self._embed_fn if self._embed_type != "tfidf-fallback" else None,
                )
                logger.info(f"ChromaDB 集合已加载: {self._collection_name} ({self._collection.count()} 条)")
            except Exception:
                self._collection = self._client.create_collection(
                    name=self._collection_name,
                    embedding_function=self._embed_fn if self._embed_type != "tfidf-fallback" else None,
                    metadata={"description": "AI Security Guardian 对话知识库"},
                )
                logger.info(f"ChromaDB 集合已创建: {self._collection_name}")

            # 如果是 fallback embedding，预训练词汇表
            if self._embed_type == "tfidf-fallback" and self._collection.count() > 0:
                existing = self._collection.get()
                if existing and existing.get("documents"):
                    self._embed_fn.fit(existing["documents"])

        except ImportError:
            logger.warning("chromadb 未安装，知识库功能降级为纯文件模式")
            logger.warning("安装: pip install chromadb")
            self._client = None
            self._collection = None

    # ================================================================
    #  写入
    # ================================================================

    def add_conversation(self, messages: List[Dict[str, str]],
                         metadata: Dict[str, Any] = None) -> Optional[str]:
        """添加对话到知识库。

        1. 保存为 Markdown 文件
        2. 按 Q&A 分块
        3. 向量化存储到 ChromaDB

        返回: 对话 ID (文件路径 stem)
        """
        # 1. 保存 Markdown
        md_path = self.store.save(messages, metadata)
        if md_path is None:
            return None

        conv_id = md_path.stem

        # 2. 分块 — 每个 Q&A 对作为一个文档
        chunks = self._chunk_conversation(messages, conv_id)

        if not chunks or self._collection is None:
            return conv_id

        # 3. 向量化存储
        try:
            ids = []
            documents = []
            metadatas = []
            for i, chunk in enumerate(chunks):
                chunk_id = f"{conv_id}_{i}"
                ids.append(chunk_id)
                documents.append(chunk["text"])
                metadatas.append({
                    "conversation_id": conv_id,
                    "timestamp": metadata.get("timestamp", "") if metadata else "",
                    "topics": ", ".join(chunk.get("topics", [])),
                    "chunk_index": i,
                    "role": chunk.get("role", "mixed"),
                })

            self._collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info(f"知识库已索引: {conv_id} ({len(chunks)} 个分块)")
        except Exception as e:
            logger.error(f"ChromaDB 写入失败: {e}")

        return conv_id

    def _chunk_conversation(self, messages: List[Dict[str, str]],
                            conv_id: str) -> List[Dict[str, Any]]:
        """将对话切分为 Q&A 分块。

        每个 Q&A 对 = 一个用户问题 + AI 回答。
        系统消息和单独的消息也保留。
        """
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

    # ================================================================
    #  检索
    # ================================================================

    def search(self, query: str, top_k: int = 5,
               filter_topics: List[str] = None) -> List[Dict[str, Any]]:
        """语义搜索知识库。

        参数:
          query: 搜索查询
          top_k: 返回结果数
          filter_topics: 可选的话题过滤

        返回: [{id, text, metadata, score}, ...]
        """
        if self._collection is None or self._collection.count() == 0:
            return self._fallback_search(query, top_k)

        try:
            where_filter = None
            if filter_topics:
                where_filter = {
                    "$or": [{"topics": {"$contains": t}} for t in filter_topics]
                }

            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, self._collection.count()),
                where=where_filter,
            )

            formatted = []
            if results and results.get("ids") and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    formatted.append({
                        "id": doc_id,
                        "text": results["documents"][0][i] if results.get("documents") else "",
                        "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                        "score": results["distances"][0][i] if results.get("distances") else 0,
                    })

            return formatted

        except Exception as e:
            logger.warning(f"ChromaDB 搜索失败: {e}，降级为关键词搜索")
            return self._fallback_search(query, top_k)

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

    # ================================================================
    #  上下文构建
    # ================================================================

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
            ts = meta.get("timestamp", "")

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

    # ================================================================
    #  管理
    # ================================================================

    @property
    def count(self) -> int:
        """知识库文档总数。"""
        if self._collection:
            return self._collection.count()
        return 0

    @property
    def conversation_count(self) -> int:
        """已保存对话文件数。"""
        return len(self.store.list_files())

    def delete_conversation(self, conv_id: str):
        """删除对话及其向量。"""
        # 删除 ChromaDB 向量
        if self._collection:
            try:
                existing = self._collection.get()
                to_delete = [eid for eid in existing.get("ids", [])
                            if eid.startswith(conv_id)]
                if to_delete:
                    self._collection.delete(ids=to_delete)
            except Exception as e:
                logger.warning(f"删除向量失败: {e}")

        # 删除 Markdown 文件
        md_path = self.conversations_dir / f"{conv_id}.md"
        if md_path.exists():
            md_path.unlink()
            logger.info(f"已删除对话: {conv_id}")

    def rebuild_index(self):
        """从 Markdown 文件重建整个向量索引。"""
        if self._collection is None:
            logger.warning("ChromaDB 不可用，无法重建索引")
            return

        # 清空现有索引
        try:
            existing = self._collection.get()
            if existing and existing.get("ids"):
                self._collection.delete(ids=existing["ids"])
        except Exception:
            pass

        # 重新索引所有对话
        for md_file in self.store.list_files():
            try:
                content = self.store.load(md_file)
                # 解析 Markdown 为消息列表
                messages = self._parse_markdown_to_messages(content)
                if messages:
                    chunks = self._chunk_conversation(messages, md_file.stem)
                    if chunks:
                        ids = []
                        documents = []
                        metadatas = []
                        for i, chunk in enumerate(chunks):
                            ids.append(f"{md_file.stem}_{i}")
                            documents.append(chunk["text"])
                            metadatas.append({
                                "conversation_id": md_file.stem,
                                "chunk_index": i,
                                "role": chunk.get("role", "mixed"),
                            })
                        self._collection.add(
                            ids=ids, documents=documents, metadatas=metadatas)
            except Exception as e:
                logger.warning(f"重新索引 {md_file.name} 失败: {e}")

        # 重新训练 fallback
        if self._embed_type == "tfidf-fallback" and self._collection.count() > 0:
            existing = self._collection.get()
            if existing and existing.get("documents"):
                self._embed_fn.fit(existing["documents"])

        logger.info(f"索引重建完成: {self._collection.count()} 条记录")

    def _parse_markdown_to_messages(self, content: str) -> List[Dict[str, str]]:
        """将保存的 Markdown 解析回消息列表。"""
        messages = []
        lines = content.split("\n")
        current_role = None
        current_content = []
        in_frontmatter = False

        for line in lines:
            if line.strip() == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                    continue
                else:
                    in_frontmatter = False
                    continue
            if in_frontmatter:
                continue

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
            elif line.startswith("## ") or line.startswith("# "):
                continue  # 跳过标题
            elif line.startswith("---") or not line.strip():
                continue  # 跳过分隔线和空行
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
            "embedding_type": self._embed_type,
            "chroma_dir": str(self.chroma_dir),
            "conversations_dir": str(self.conversations_dir),
        }


# ============================================================
# 全局单例
# ============================================================

_kb_instance: Optional[KnowledgeBase] = None


def get_knowledge_base(persist_dir: str = None) -> KnowledgeBase:
    """获取全局知识库实例 (懒加载单例)。"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase(persist_dir=persist_dir)
    return _kb_instance


def reset_knowledge_base():
    """重置知识库实例 (用于测试)。"""
    global _kb_instance
    _kb_instance = None
