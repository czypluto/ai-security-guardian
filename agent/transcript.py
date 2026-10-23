"""Append-only 对话长期副本（turn 级 JSONL）与回查。

为什么单独一层：
  - LangGraph checkpointer 是“模型状态缓存”，不是用户可浏览的对话历史；
  - knowledge_base 的 Markdown 是“检索记忆”，写入是整篇重写、格式有损；
  - 这里按 turn 追加，保留完整消息（含工具调用与结果），供 UI 展示和回查。

文件布局::

    data/transcripts/<conversation_id>.jsonl

一行一个 turn::

    {"turn_id": "t-...", "conversation_id": "...", "ts": "...", "messages": [...]}

只追加、不覆盖。最后一行写坏时读取会跳过它，不影响前面的记录。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from langchain_core.messages import BaseMessage

from .bm25 import Bm25Index
from .graph_model import dicts_to_messages, messages_to_dicts

logger = logging.getLogger("Guardian.Transcript")

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _default_dir() -> Path:
    env = os.getenv("GUARDIAN_TRANSCRIPT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "transcripts"


def _message_records(messages: Sequence[BaseMessage]) -> List[dict]:
    """BaseMessage -> OpenAI dict，并额外保留 message id。"""
    records = messages_to_dicts(messages)
    for record, message in zip(records, messages):
        if getattr(message, "id", None):
            record["id"] = message.id
    return records


def _turn_text(record: dict) -> str:
    """一个 turn 的可检索文本（用户/助手/工具内容拼接）。"""
    parts: List[str] = []
    for message in record.get("messages") or []:
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(
                str(p.get("text", "")) if isinstance(p, dict) else str(p)
                for p in content
            )
        parts.append(str(content))
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            parts.append(str(fn.get("name", "")))
            parts.append(str(fn.get("arguments", "")))
        if message.get("name"):
            parts.append(str(message["name"]))
    return "\n".join(parts)


class TranscriptStore:
    """按 conversation_id 分文件的 turn 级长期副本。"""

    def __init__(self, base_dir: Optional[str] = None):
        # 懒创建目录：只读/未归档的会话不应在磁盘上留下副作用。
        self.base_dir = Path(base_dir) if base_dir else _default_dir()
        self._lock = threading.Lock()
        self._seen_turns: Dict[str, set] = {}
        self._bm25: Dict[str, Bm25Index] = {}
        self._bm25_turns: Dict[str, Dict[str, dict]] = {}

    # ---- 路径 ----

    def _path(self, conversation_id: str) -> Path:
        if not _SAFE_ID.match(conversation_id or ""):
            raise ValueError(f"非法 conversation_id: {conversation_id!r}")
        return self.base_dir / f"{conversation_id}.jsonl"

    def path_for(self, conversation_id: str) -> str:
        """公开的路径查询（写索引时用）。"""
        return str(self._path(conversation_id))

    def _known_turns(self, conversation_id: str) -> set:
        if conversation_id in self._seen_turns:
            return self._seen_turns[conversation_id]
        known = set()
        for record in self.load_turns(conversation_id):
            known.add(record.get("turn_id", ""))
        self._seen_turns[conversation_id] = known
        return known

    # ---- 写入 ----

    def append_turn(self, conversation_id: str, turn_id: str,
                    messages: Sequence[BaseMessage]) -> bool:
        """追加一个 turn；重复 turn_id 幂等跳过。返回是否真的写入。"""
        if not conversation_id or not turn_id or not messages:
            return False

        path = self._path(conversation_id)
        record = {
            "turn_id": turn_id,
            "conversation_id": conversation_id,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "messages": _message_records(messages),
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            if turn_id in self._known_turns(conversation_id):
                return False
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
            self._seen_turns.setdefault(conversation_id, set()).add(turn_id)
            self._bm25.pop(conversation_id, None)
            self._bm25_turns.pop(conversation_id, None)
        logger.info("transcript: %s / %s (%d msgs)",
                    conversation_id, turn_id, len(messages))
        return True

    # ---- 读取 ----

    def load_turns(self, conversation_id: str) -> List[dict]:
        path = self._path(conversation_id)
        if not path.is_file():
            return []
        turns: List[dict] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("transcript: 跳过损坏行 %s", path.name)
                        continue
                    if isinstance(record, dict):
                        turns.append(record)
        except OSError as e:
            logger.warning("transcript 读取失败(%s)", e)
        return turns

    def load_messages(self, conversation_id: str) -> List[BaseMessage]:
        """把整个会话还原成 langchain 消息，供 UI 展示或重建 state。"""
        records: List[dict] = []
        for turn in self.load_turns(conversation_id):
            records.extend(turn.get("messages") or [])
        return dicts_to_messages(records)

    def list_conversation_ids(self) -> List[str]:
        return sorted(p.stem for p in self.base_dir.glob("*.jsonl"))

    # ---- 回查 ----

    def _ensure_index(self, conversation_id: str) -> Bm25Index:
        if conversation_id in self._bm25:
            return self._bm25[conversation_id]
        turns = {
            str(t.get("turn_id", "")): t
            for t in self.load_turns(conversation_id)
            if t.get("turn_id")
        }
        texts = {tid: _turn_text(t) for tid, t in turns.items()}
        self._bm25_turns[conversation_id] = turns
        self._bm25[conversation_id] = Bm25Index().build(texts)
        return self._bm25[conversation_id]

    def search(self, conversation_id: str, query: str,
               limit: int = 5) -> List[dict]:
        """BM25 回查当前会话历史，返回 turn_id / 时间 / 片段。"""
        if not query:
            return []
        try:
            index = self._ensure_index(conversation_id)
            hits = index.search(query, top_k=max(1, limit))
        except Exception as e:  # noqa: BLE001 - 回查失败不应影响主流程
            logger.warning("transcript 检索失败(%s)", e)
            return []

        turns = self._bm25_turns.get(conversation_id, {})
        out: List[dict] = []
        for turn_id, score in hits:
            turn = turns.get(turn_id)
            if not turn:
                continue
            out.append({
                "turn_id": turn_id,
                "ts": turn.get("ts", ""),
                "snippet": _turn_text(turn)[:1200],
                "score": score,
            })
        return out
