"""
Knowledge Base — 本地知识库（纯 BM25 关键词检索）

功能:
  - 对话保存为 Markdown 文件（**事实源**，索引丢了也能重建）
  - 按 Q&A 切块，构建中文 BM25 索引
  - 检索历史对话，为 LLM 构建上下文增强提示

为什么没有向量检索:
  - 语料是本地单人积累的几十~几千条对话，BM25 的精确词面召回更贴合
    安全场景里的进程名、端口号、CVE 编号这类 token；
  - 向量路要额外拉起嵌入模型（GPU 显存、20~90s 冷启动），
    在这个数据规模上收益与运维成本不匹配；
  - 索引是派生物：Markdown 永远是真源，删掉重建即可。

架构:
  knowledge_base/
  └── conversations/     # Markdown 对话文件 (始终保留)

线程安全: BM25 索引是进程内纯 Python 结构，可后台线程安全调用。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .bm25 import Bm25Index

logger = logging.getLogger("Guardian.KB")


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
        stem = now.strftime("%Y-%m-%d_%H%M%S")
        filepath = self.base_dir / f"{stem}.md"
        # 同一秒内连续保存会撞名：加后缀而不是覆盖，否则会静默丢历史。
        n = 2
        while filepath.exists():
            filepath = self.base_dir / f"{stem}_{n}.md"
            n += 1

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
    """本地知识库 — 中文 BM25 检索历史对话。

    Markdown 是事实源；BM25 索引是进程内派生物，语料变动时懒重建。
    """

    def __init__(self, persist_dir: str = None):
        """参数:
          persist_dir: 持久化目录，默认项目根目录下的 knowledge_base/
        """
        if persist_dir is None:
            persist_dir = Path(__file__).parent.parent / "knowledge_base"
        self.persist_dir = Path(persist_dir)
        self.conversations_dir = self.persist_dir / "conversations"
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)

        # Conversation store (Markdown，永远可用)
        self.store = ConversationStore(self.conversations_dir)

        # 中文 BM25 — 懒加载；语料变动时置 None 触发重建
        self._bm25: Optional[Bm25Index] = None
        self._bm25_chunks: Dict[str, Dict[str, Any]] = {}

    # 写入

    def add_conversation(self, messages: List[Dict[str, str]],
                         metadata: Dict[str, Any] = None) -> Optional[str]:
        """添加对话到知识库。

        1. 保存为 Markdown 文件（事实源）
        2. 下一轮检索时按 Q&A 懒重建 BM25 索引

        返回: 对话 ID (文件路径 stem)
        """
        md_path = self.store.save(messages, metadata)
        if md_path is None:
            return None

        self._bm25 = None  # 语料已变，BM25 索引下轮懒重建
        return md_path.stem

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

        语料取自 Markdown（事实源）。doc_id 为 ``{conv_id}_{i}``，
        语料变动（新增/删除对话）时把 ``self._bm25`` 置 None 即触发重建。
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
        """中文 BM25 召回，返回统一的 hit 结构。"""
        index = self._ensure_bm25_index()
        allow = None
        if filter_topics:
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
        """纯中文 BM25 关键词检索。

        返回: [{id, text, metadata, score}, ...]；score 为 BM25 分。
        """
        if not query:
            return []
        try:
            return self._bm25_search(query, top_k=top_k,
                                     filter_topics=filter_topics)
        except Exception as e:  # noqa: BLE001 - 检索失败不该让整轮报错
            logger.warning("BM25 检索失败(%s)", e)
            return []

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
    def conversation_count(self) -> int:
        """已保存对话文件数。"""
        return len(self.store.list_files())

    def delete_conversation(self, conv_id: str):
        """删除对话的 Markdown 文件；下次检索时重建 BM25 索引。"""
        md_path = self.conversations_dir / f"{conv_id}.md"
        if md_path.exists():
            md_path.unlink()
            logger.info(f"已删除对话: {conv_id}")

        self._bm25 = None  # 语料已变，索引下轮懒重建

    def rebuild_index(self):
        """丢弃内存索引；下次检索时从 Markdown 重建。"""
        self._bm25 = None
        self._bm25_chunks = {}
        logger.info("BM25 索引已重置，下次检索时重建")

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
            "bm25_chunks": len(self._ensure_bm25_index()) if self.conversation_count else 0,
            "storage_dir": str(self.conversations_dir),
            "conversations_dir": str(self.conversations_dir),
        }


# 全局单例

_kb_instance: Optional[KnowledgeBase] = None
_kb_lock = threading.Lock()


def get_knowledge_base(persist_dir: str = None) -> KnowledgeBase:
    """获取全局知识库实例 (懒加载单例，线程安全)。"""
    global _kb_instance
    if _kb_instance is None:
        with _kb_lock:
            if _kb_instance is None:
                _kb_instance = KnowledgeBase(persist_dir=persist_dir)
    return _kb_instance


def reset_knowledge_base():
    """重置知识库实例 (用于测试)。"""
    global _kb_instance
    _kb_instance = None
