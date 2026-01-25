"""Dashboard API for Chiffon web interface.

Provides:
- Chat session management
- Plan review and approval workflows
- Real-time execution updates
"""

from .api import router as dashboard_router
from .models import (
    ChatMessage,
    ChatSession,
    DashboardPlanView,
    ExecutionUpdate,
    ModificationRequest,
    SessionStore,
)

__all__ = [
    "dashboard_router",
    "ChatSession",
    "ChatMessage",
    "DashboardPlanView",
    "ModificationRequest",
    "ExecutionUpdate",
    "SessionStore",
]
