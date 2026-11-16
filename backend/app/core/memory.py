"""多轮对话记忆管理。

对齐文档要求：
- 仅在内存中缓存当前会话内容，不持久化冗余历史；
- 限制记忆长度（默认最近 5 轮），防止内存累积；
- 支持多会话隔离、单会话清空。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from app.config import settings


@dataclass
class Turn:
    """一轮问答。"""

    question: str
    answer: str
    ts: float = field(default_factory=time.time)


@dataclass
class Session:
    """单个会话。"""

    id: str
    created_at: float = field(default_factory=time.time)
    turns: list[Turn] = field(default_factory=list)

    def history_messages(self, rounds: int) -> list[dict]:
        """取最近 rounds 轮，转成 OpenAI 消息格式。"""
        recent = self.turns[-rounds:] if rounds > 0 else []
        msgs: list[dict] = []
        for t in recent:
            msgs.append({"role": "user", "content": t.question})
            msgs.append({"role": "assistant", "content": t.answer})
        return msgs


class MemoryStore:
    """进程内会话表，线程安全。"""

    def __init__(self, max_sessions: int = 50) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._max = max_sessions

    def create(self, session_id: str | None = None) -> Session:
        sid = session_id or uuid.uuid4().hex[:12]
        with self._lock:
            if sid not in self._sessions:
                self._sessions[sid] = Session(id=sid)
            self._evict_locked()
            return self._sessions[sid]

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def append(self, session_id: str, question: str, answer: str) -> Session:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                # 直接 append 未知 session 时会新建，这里必须同样触发淘汰，
                # 否则前端每轮新开会话会导致会话表无限增长（内存泄漏）
                sess = Session(id=session_id)
                self._sessions[session_id] = sess
                self._evict_locked()

            sess.turns.append(Turn(question=question, answer=answer))
            # 只保留最近 20 轮，超出部分丢弃，控制内存
            if len(sess.turns) > 20:
                sess.turns = sess.turns[-20:]
            return sess

    def clear(self, session_id: str) -> bool:
        """清空某会话的对话内容（保留会话本身）。"""
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                return False
            sess.turns.clear()
            return True

    def drop(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "id": s.id,
                    "turns": len(s.turns),
                    "created_at": s.created_at,
                    "last_at": s.turns[-1].ts if s.turns else s.created_at,
                }
                # 按最近活跃排序，而不是创建时间，更符合「最近会话」的直觉
                for s in sorted(
                    self._sessions.values(),
                    key=lambda x: x.turns[-1].ts if x.turns else x.created_at,
                    reverse=True,
                )
            ]

    def _evict_locked(self) -> None:
        """会话数超限时，淘汰最久未活跃的会话。"""
        if len(self._sessions) <= self._max:
            return
        ordered = sorted(
            self._sessions.values(),
            key=lambda s: s.turns[-1].ts if s.turns else s.created_at,
        )
        for s in ordered[: len(self._sessions) - self._max]:
            self._sessions.pop(s.id, None)


memory = MemoryStore()


def history_for(session_id: str | None) -> list[dict]:
    """取指定会话的近期上下文消息。"""
    if not session_id:
        return []
    sess = memory.get(session_id)
    if not sess:
        return []
    return sess.history_messages(settings.memory_rounds)
