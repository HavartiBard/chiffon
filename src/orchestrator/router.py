"""Agent routing and intelligent task-to-agent matching.

Provides:
- AgentRouter: Routes tasks to best available agents based on performance and specialization
- AgentSelection: Result of routing decision with explanation
- Scoring algorithm: Success rate (40pts) + context (30pts) + specialization (20pts) + load (10pts)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.common.models import (
    AgentPerformance,
    AgentRegistry,
    RoutingDecision,
    WorkTask,
)

logger = logging.getLogger(__name__)


class AgentSelection(BaseModel):
    """Result of agent routing decision."""

    agent_id: UUID = Field(description="Selected agent ID")
    agent_type: str = Field(description="Agent type (infra|code|research|desktop)")
    pool_name: str = Field(description="Agent pool name")
    selected_reason: str = Field(description="Explanation of why this agent was selected")
    score: int = Field(ge=0, le=100, description="Routing score 0-100")


class AgentRouter:
    """Intelligent agent routing based on performance and specialization."""

    def __init__(self, db: Session, logger_instance: Optional[logging.Logger] = None):
        """Initialize router with database session.

        Args:
            db: SQLAlchemy session
            logger_instance: Optional logger (uses module logger if not provided)
        """
        self.db = db
        self.logger = logger_instance or logger

    async def route_task(self, task: WorkTask, retry_count: int = 0) -> AgentSelection:
        """Route a task to the best available agent.

        Scoring algorithm (0-100 points):
        - Success rate: +40 (based on success_count/(success+failure) ratio)
        - Recent context: +30 (executed same work_type in last 4 hours)
        - Specialization: +20 (agent has specialization for this work type)
        - Load balancing: +10 - (current_load/10) (prefer less loaded agents)
        - Minimum sample: Only use success rate if >10 total executions

        Args:
            task: WorkTask to route
            retry_count: Current retry attempt number (0 for first attempt)

        Returns:
            AgentSelection with selected agent and explanation

        Raises:
            ValueError: If no agents available or agent pool offline
        """
        # Find candidate agents: same type, online/idle, with capability
        candidates = (
            self.db.query(AgentRegistry)
            .filter(
                AgentRegistry.agent_type == task.agent_type,
                AgentRegistry.status.in_(["online", "idle"]),
            )
            .all()
        )

        if not candidates:
            raise ValueError(
                f"Agent pool {task.agent_type} offline/empty. "
                f"Cannot proceed without available agents."
            )

        # Filter to agents with required capability
        capable_agents = [
            agent for agent in candidates if task.work_type in (agent.capabilities or [])
        ]

        if not capable_agents:
            raise ValueError(
                f"No agents in pool {task.agent_type} have capability {task.work_type}"
            )

        # Score each candidate
        scored_agents = []
        for agent in capable_agents:
            score = self._score_agent(agent, task)
            scored_agents.append((agent, score))

        # Select agent with highest score
        best_agent, best_score = max(scored_agents, key=lambda x: x[1])

        # Build selection reason
        reason = self._build_selection_reason(best_agent, task, best_score, retry_count)

        # Log routing decision
        self._log_routing_decision(task, best_agent, best_score, retry_count, reason)

        self.logger.info(
            f"Routed {task.work_type} to {best_agent.agent_id} "
            f"(score={best_score}, pool={best_agent.pool_name}, "
            f"context={self._check_recent_context(best_agent.agent_id, task.work_type)})"
        )

        return AgentSelection(
            agent_id=best_agent.agent_id,
            agent_type=best_agent.agent_type,
            pool_name=best_agent.pool_name,
            selected_reason=reason,
            score=best_score,
        )

    async def dispatch_with_retry(self, task: WorkTask, max_retries: int = 3) -> dict:
        """Dispatch task with automatic retry on failure.

        Retries on agent failure up to max_retries times.
        If agent pool offline or missing capability, fails immediately without retry.

        Args:
            task: WorkTask to dispatch
            max_retries: Maximum retry attempts (default 3)

        Returns:
            dict with dispatch result

        Raises:
            ValueError: If all retries exhausted or pool offline
        """
        for attempt in range(max_retries):
            try:
                selection = await self.route_task(task, retry_count=attempt)

                # Dispatch to agent (would use RabbitMQ in full implementation)
                result = {
                    "task_id": task.order,
                    "agent_id": selection.agent_id,
                    "status": "dispatched",
                    "attempt": attempt + 1,
                }

                self.logger.info(
                    f"Task dispatched to {selection.agent_id} on attempt {attempt + 1}"
                )
                return result

            except ValueError as e:
                # Permanent error - don't retry
                if "offline" in str(e).lower() or "capability" in str(e).lower():
                    self.logger.error(f"Permanent error, not retrying: {e}", exc_info=True)
                    raise

                # Transient error - retry
                if attempt < max_retries - 1:
                    self.logger.warning(
                        f"Attempt {attempt + 1} failed ({e}), retrying with different agent"
                    )
                else:
                    self.logger.error(
                        f"All {max_retries} attempts failed for {task.work_type}: {e}",
                        exc_info=True,
                    )
                    raise ValueError(f"Failed to dispatch task after {max_retries} retries: {e}")

        # Should not reach here
        raise ValueError("Unexpected error: all retries exhausted")

    def _score_agent(self, agent: AgentRegistry, task: WorkTask) -> int:
        """Calculate routing score for an agent (0-100).

        Args:
            agent: Agent to score
            task: Task being routed

        Returns:
            Score 0-100
        """
        score = 0

        # Success rate: +40 (if minimum sample size met)
        perf = (
            self.db.query(AgentPerformance)
            .filter(
                AgentPerformance.agent_id == agent.agent_id,
                AgentPerformance.work_type == task.work_type,
            )
            .first()
        )

        if perf:
            total_executions = perf.success_count + perf.failure_count
            if total_executions >= 10:  # Minimum sample size
                success_rate = self._calculate_success_rate(perf)
                score += int(40 * success_rate)
            else:
                # New agent or low sample: use neutral default
                score += 20  # 50% of max (40 * 0.5)
        else:
            # No performance data yet
            score += 20  # 50% of max

        # Recent context: +30 (executed same work type in last 4 hours)
        if self._check_recent_context(agent.agent_id, task.work_type, hours=4):
            score += 30

        # Specialization match: +20
        if agent.specializations and task.work_type in agent.specializations:
            score += 20

        # Load balancing: +10 - (current_load/10)
        load = self._estimate_load(agent.agent_id)
        load_score = max(0, 10 - (load // 10))
        score += load_score

        return min(score, 100)  # Cap at 100

    def _check_recent_context(self, agent_id: UUID, work_type: str, hours: int = 4) -> bool:
        """Check if agent recently executed this work type.

        Args:
            agent_id: Agent ID
            work_type: Work type to check
            hours: Time window in hours (default 4)

        Returns:
            True if agent executed this work type in the time window
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = (
            self.db.query(RoutingDecision)
            .filter(
                RoutingDecision.selected_agent_id == agent_id,
                RoutingDecision.work_type == work_type,
                RoutingDecision.created_at > cutoff_time,
            )
            .first()
        )
        return recent is not None

    def _estimate_load(self, agent_id: UUID) -> int:
        """Estimate current load for an agent.

        Counts routing decisions for this agent in last 1 hour.
        Returns count (0-10 scale, capped at 10).

        Args:
            agent_id: Agent ID

        Returns:
            Load estimate 0-10
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        count = (
            self.db.query(RoutingDecision)
            .filter(
                RoutingDecision.selected_agent_id == agent_id,
                RoutingDecision.created_at > cutoff_time,
            )
            .count()
        )
        return min(count, 10)

    def _calculate_success_rate(self, perf: AgentPerformance) -> float:
        """Calculate success rate avoiding division by zero.

        Args:
            perf: AgentPerformance record

        Returns:
            Success rate 0.0-1.0 (0.5 default if no data)
        """
        total = perf.success_count + perf.failure_count
        if total == 0:
            return 0.5  # Neutral default
        return perf.success_count / total

    def _log_routing_decision(
        self,
        task: WorkTask,
        agent: AgentRegistry,
        score: int,
        retry_count: int,
        reason: str,
    ) -> None:
        """Log routing decision to database.

        Args:
            task: Task being routed
            agent: Selected agent
            score: Routing score
            retry_count: Retry attempt number
            reason: Explanation of selection
        """
        perf = (
            self.db.query(AgentPerformance)
            .filter(
                AgentPerformance.agent_id == agent.agent_id,
                AgentPerformance.work_type == task.work_type,
            )
            .first()
        )

        success_rate_percent = None
        if perf:
            total = perf.success_count + perf.failure_count
            if total >= 10:
                success_rate_percent = int(100 * self._calculate_success_rate(perf))

        specialization_match = (
            1 if agent.specializations and task.work_type in agent.specializations else 0
        )

        recent_context_match = (
            1 if self._check_recent_context(agent.agent_id, task.work_type) else 0
        )

        decision = RoutingDecision(
            task_id=None,  # Would be set by orchestrator
            work_type=task.work_type,
            agent_pool=agent.pool_name,
            selected_agent_id=agent.agent_id,
            success_rate_percent=success_rate_percent,
            specialization_match=specialization_match,
            recent_context_match=recent_context_match,
            retried=1 if retry_count > 0 else 0,
            reason=reason,
        )

        self.db.add(decision)
        self.db.commit()

        self.logger.debug(
            f"Logged routing decision for task {task.work_type} " f"to agent {agent.agent_id}"
        )

    def _build_selection_reason(
        self, agent: AgentRegistry, task: WorkTask, score: int, retry_count: int
    ) -> str:
        """Build human-readable explanation of routing decision.

        Args:
            agent: Selected agent
            task: Task being routed
            score: Routing score
            retry_count: Retry attempt number

        Returns:
            Explanation string
        """
        reasons = []

        # Check what contributed to the score
        perf = (
            self.db.query(AgentPerformance)
            .filter(
                AgentPerformance.agent_id == agent.agent_id,
                AgentPerformance.work_type == task.work_type,
            )
            .first()
        )

        if perf:
            total = perf.success_count + perf.failure_count
            if total >= 10:
                success_rate = int(100 * self._calculate_success_rate(perf))
                reasons.append(f"{success_rate}% success rate")

        if self._check_recent_context(agent.agent_id, task.work_type):
            reasons.append("recent context")

        if agent.specializations and task.work_type in agent.specializations:
            reasons.append("specialization match")

        reason_str = ", ".join(reasons) if reasons else "available and capable"

        retry_str = f" (retry #{retry_count})" if retry_count > 0 else ""
        return f"Selected based on {reason_str}{retry_str}"
