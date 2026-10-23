"""会话索引 —— conversation_id ↔ thread_id ↔ transcript 的持久映射。

transcript 是事实源，但它的文件名不足以支撑“历史列表”：标题、更新时间、
消息数、当前 thread 都需要单独维护。这里用一个很小的 JSON 索引，原子写入。

索引不存对话内容，只存元数据；内容永远在 transcript JSONL 里。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Guardian.Conversations")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_dir() -> Path:
    env = os.getenv("GUARDIAN_CONVERSATION_INDEX_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "conversations"


@dataclass
class ConversationMeta:
    conversation_id: str
    thread_id: str
    title: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    message_count: int = 0
    transcript_path: str = ""
    status: str = "active"          # active | archived

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationMeta":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


class ConversationIndex:
    """线程安全的 JSON 索引。"""

    def __init__(self, base_dir: Optional[str] = None):
        # 懒创建目录：仅构造 AgentCore 时不应写盘。
        self.base_dir = Path(base_dir) if base_dir else _default_dir()
        self.path = self.base_dir / "index.json"
        self._lock = threading.Lock()
        self._items: Dict[str, ConversationMeta] = {}
        self._loaded = False

    # ---- 持久化 ----

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            items = raw.get("conversations", raw) if isinstance(raw, dict) else {}
            self._items = {
                cid: ConversationMeta.from_dict(meta)
                for cid, meta in items.items()
                if isinstance(meta, dict)
            }
        except Exception as e:  # noqa: BLE001 - 索引坏了不应阻止启动
            logger.warning("会话索引载入失败(%s)，按空索引继续", e)
            self._items = {}

    def _save(self) -> None:
        payload = {
            "version": 1,
            "conversations": {cid: m.to_dict() for cid, m in self._items.items()},
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
        except Exception as e:  # noqa: BLE001
            logger.warning("会话索引写入失败(%s)", e)

    # ---- CRUD ----

    def create(self, conversation_id: str, thread_id: str,
               title: str = "", transcript_path: str = "") -> ConversationMeta:
        with self._lock:
            self._load()
            now = _now()
            meta = ConversationMeta(
                conversation_id=conversation_id,
                thread_id=thread_id,
                title=title,
                created_at=now,
                updated_at=now,
                transcript_path=transcript_path,
            )
            self._items[conversation_id] = meta
            self._save()
            return meta

    def get(self, conversation_id: str) -> Optional[ConversationMeta]:
        with self._lock:
            self._load()
            return self._items.get(conversation_id)

    def list(self, include_archived: bool = False) -> List[ConversationMeta]:
        with self._lock:
            self._load()
            items = [
                m for m in self._items.values()
                if include_archived or m.status == "active"
            ]
        return sorted(items, key=lambda m: m.updated_at, reverse=True)

    def update(self, conversation_id: str, **fields: Any) -> Optional[ConversationMeta]:
        with self._lock:
            self._load()
            meta = self._items.get(conversation_id)
            if meta is None:
                return None
            for key, value in fields.items():
                if key in ConversationMeta.__dataclass_fields__:
                    setattr(meta, key, value)
            meta.updated_at = _now()
            self._save()
            return meta

    def record_turn(self, conversation_id: str, message_count: int,
                    title: str = "") -> Optional[ConversationMeta]:
        """一轮归档后更新索引：累加消息数，必要时补标题。"""
        with self._lock:
            self._load()
            meta = self._items.get(conversation_id)
            if meta is None:
                return None
            meta.message_count += max(0, message_count)
            if title and not meta.title:
                meta.title = title[:60]
            meta.updated_at = _now()
            self._save()
            return meta


def title_from_messages(messages: List[Any]) -> str:
    """取第一条用户消息做标题。"""
    for message in messages:
        if getattr(message, "type", "") == "human":
            content = getattr(message, "content", "")
            text = content if isinstance(content, str) else str(content)
            text = " ".join(text.split())
            if text:
                return text[:60]
    return ""
