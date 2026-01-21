"""Audit service for querying task execution history.

Provides methods for:
- Querying failures in time range (STATE-03: "all failures in last week")
- Querying by service name (STATE-03: "all changes to service X")
- Combined filtering (status + time + service)
- Intent inference from outcome JSON
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.common.models import Task

logger = logging.getLogger(__name__)


class AuditService:
    """Service for querying task audit records.

    Uses GIN index on services_touched for efficient array containment queries.
    Uses composite index on (status, created_at) for time-range queries.
    """

    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger("orchestrator.audit")

    def get_failures(
        self,
        days: int = 7,
        service: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Task]:
        """Get failed tasks in the specified time range.

        Implements STATE-03: "all failures in last week"

        Args:
            days: Look back N days (default 7)
            service: Optional service name filter
            limit: Max results (default 100)
            offset: Pagination offset (default 0)

        Returns:
            List of failed Task records, newest first
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = self.db.query(Task).filter(
            Task.status == "failed",
            Task.created_at > cutoff,
        )

        if service:
            # Use GIN index with contains() operator
            query = query.filter(Task.services_touched.contains([service]))

        self.logger.info(
            f"Querying failures: days={days}, service={service}, limit={limit}"
        )

        return (
            query.order_by(desc(Task.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_by_service(
        self,
        service_name: str,
        status: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Task]:
        """Get all tasks that touched a specific service.

        Implements STATE-03: "all changes to service X"

        Args:
            service_name: Service name to filter by
            status: Optional status filter
            days: Optional time range in days
            limit: Max results (default 100)
            offset: Pagination offset (default 0)

        Returns:
            List of Task records touching this service, newest first
        """
        # Use GIN index with contains() operator - NOT any()
        query = self.db.query(Task).filter(
            Task.services_touched.contains([service_name])
        )

        if status:
            query = query.filter(Task.status == status)

        if days:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Task.created_at > cutoff)

        self.logger.info(
            f"Querying by service: service={service_name}, status={status}, days={days}"
        )

        return (
            query.order_by(desc(Task.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def audit_query(
        self,
        status: Optional[str] = None,
        service: Optional[str] = None,
        intent: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Task]:
        """Combined audit query with multiple optional filters.

        Supports combined filtering: status + time range + service + intent.
        Intent is inferred from outcome JSON field (action_type).

        Args:
            status: Filter by task status
            service: Filter by service in services_touched
            intent: Filter by action type in outcome JSON
            days: Filter by time range
            limit: Max results
            offset: Pagination offset

        Returns:
            List of matching Task records, newest first
        """
        query = self.db.query(Task)

        if status:
            query = query.filter(Task.status == status)

        if service:
            query = query.filter(Task.services_touched.contains([service]))

        if days:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Task.created_at > cutoff)

        if intent:
            # Infer intent from outcome JSON using JSONB path
            query = query.filter(
                Task.outcome["action_type"].astext == intent
            )

        self.logger.info(
            f"Audit query: status={status}, service={service}, intent={intent}, days={days}"
        )

        return (
            query.order_by(desc(Task.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_task_count(
        self,
        status: Optional[str] = None,
        service: Optional[str] = None,
        days: Optional[int] = None,
    ) -> int:
        """Get count of matching tasks for pagination.

        Args:
            status: Optional status filter
            service: Optional service filter
            days: Optional time range

        Returns:
            Count of matching tasks
        """
        query = self.db.query(Task)

        if status:
            query = query.filter(Task.status == status)

        if service:
            query = query.filter(Task.services_touched.contains([service]))

        if days:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Task.created_at > cutoff)

        return query.count()
