"""Small in-process session store for the synchronous Chat API."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from typing import Any

from agent.main_agent.context import AgentContext


@dataclass
class ChatSession:
    session_id: str
    context: AgentContext
    lock: RLock = field(default_factory=RLock)
    responses: OrderedDict[str, tuple[str, dict[str, Any]]] = field(default_factory=OrderedDict)
    touched_at: float = field(default_factory=monotonic)

    def cached_response(self, request_id: str, message: str) -> dict[str, Any] | None:
        entry = self.responses.get(request_id)
        if entry is not None:
            self.responses.move_to_end(request_id)
            original_message, response = entry
            if original_message != message:
                raise ValueError("request_id was already used with a different message")
            return response
        return None

    def cache_response(
        self,
        request_id: str,
        message: str,
        response: dict[str, Any],
        *,
        limit: int = 100,
    ) -> None:
        self.responses[request_id] = (message, response)
        self.responses.move_to_end(request_id)
        while len(self.responses) > limit:
            self.responses.popitem(last=False)


class ChatSessionStore:
    """Own process-local chat contexts and serialize turns within each session."""

    def __init__(self, *, ttl_seconds: int = 6 * 60 * 60, max_sessions: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._lock = RLock()
        self._sessions: dict[str, ChatSession] = {}

    def get_or_create(self, session_id: str) -> ChatSession:
        with self._lock:
            now = monotonic()
            self._discard_expired(now)
            session = self._sessions.get(session_id)
            if session is None:
                session = ChatSession(
                    session_id=session_id,
                    context=AgentContext(
                        session_id=f"web-chat:{session_id}",
                        workspace_id=f"web-chat:{session_id}",
                    ),
                )
                self._sessions[session_id] = session
                self._discard_oldest()
            session.touched_at = now
            return session

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _discard_expired(self, now: float) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.touched_at > self.ttl_seconds
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def _discard_oldest(self) -> None:
        while len(self._sessions) > self.max_sessions:
            oldest = min(self._sessions.values(), key=lambda item: item.touched_at)
            self._sessions.pop(oldest.session_id, None)
