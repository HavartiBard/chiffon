"""Pydantic models powering the dashboard API and session tracking."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None


class ChatSession(BaseModel):
    session_id: str
    user_id: str
    created_at: datetime
    last_activity: datetime
    messages: List[ChatMessage] = Field(default_factory=list)
    current_request_id: Optional[str] = None
    current_plan_id: Optional[str] = None
    status: Literal["idle", "awaiting_plan", "plan_ready", "executing", "completed"] = "idle"
    active_task_ids: List[str] = Field(default_factory=list)


class PlanStepView(BaseModel):
    index: int
    name: str
    description: str
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    duration_ms: Optional[int] = None
    completed: bool = False
    metadata: Optional[Dict[str, Any]] = None


class DashboardPlanView(BaseModel):
    plan_id: str
    request_id: str
    summary: str
    steps: List[PlanStepView]
    estimated_duration: str
    risk_level: Literal["low", "medium", "high"]
    resource_requirements: Dict[str, Any]
    status: str
    can_approve: bool
    can_modify: bool
    can_abort: bool


class ModificationRequest(BaseModel):
    plan_id: str
    user_message: str
    session_id: str


class ExecutionUpdate(BaseModel):
    plan_id: str
    step_index: int
    step_name: str
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SessionStore:
    """In-memory chat session storage for dashboard interactions."""

    def __init__(self) -> None:
        self._sessions: Dict[str, ChatSession] = {}
        self._lock = Lock()
        self.logger = logging.getLogger("dashboard.session")

    def create_session(self, user_id: str) -> ChatSession:
        session = ChatSession(
            session_id=str(uuid4()),
            user_id=user_id,
            created_at=datetime.utcnow(),
            last_activity=datetime.utcnow(),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        self.logger.info("Created new session", extra={"session_id": session.session_id})
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        with self._lock:
            session = self._sessions.get(session_id)
        if session:
            return session
        self.logger.debug("Session not found", extra={"session_id": session_id})
        return None

    def add_message(self, session_id: str, message: ChatMessage) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError("Session not found")
            session.messages.append(message)
            session.last_activity = datetime.utcnow()

    def update_session_status(self, session_id: str, status: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError("Session not found")
            session.status = status
            session.last_activity = datetime.utcnow()

    def cleanup_expired(self, max_age_hours: int = 24) -> int:
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=max_age_hours)
        removed = []
        with self._lock:
            for session_id, session in list(self._sessions.items()):
                if session.last_activity < cutoff:
                    removed.append(session_id)
                    del self._sessions[session_id]
        if removed:
            self.logger.info("Cleaned up expired sessions", extra={"count": len(removed)})
        return len(removed)

    def clear(self) -> None:
        """Remove all sessions (helpful for tests)."""
        with self._lock:
            self._sessions.clear()
