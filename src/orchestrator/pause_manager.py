"""PauseManager: Resource-aware pause/resume lifecycle for work dispatch.

Provides:
- Pre-dispatch capacity checking to prevent overload
- Pause persistence for work awaiting resources
- Background polling to resume work when capacity recovers
- Graceful shutdown and error recovery
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from src.common.models import AgentRegistry, PauseQueueEntry, Task

logger = logging.getLogger(__name__)


class PauseManager:
    """Manages pause/resume of work based on agent capacity constraints.

    Monitors available capacity across agent pools and pauses work dispatch
    when all agents fall below a configurable threshold. Persists paused work
    to a database queue and resumes it when capacity recovers.

    Runs background polling task to continuously check for capacity recovery.
    """

    def __init__(self, db: Session, capacity_threshold_percent: float = 0.2):
        """Initialize PauseManager with database session and capacity threshold.

        Args:
            db: SQLAlchemy session for database queries and mutations
            capacity_threshold_percent: Minimum available capacity threshold (0.0-1.0)
                                       Default 0.2 = 20% (pause if all agents <20% available)

        Environment variables:
            PAUSE_CAPACITY_THRESHOLD_PERCENT: Override threshold (0.0-1.0)
            PAUSE_POLLING_INTERVAL_SECONDS: Override polling interval (default 10)
        """
        self.db = db
        self.logger = logging.getLogger("orchestrator.pause_manager")

        # Load threshold from environment or use parameter
        env_threshold = os.getenv("PAUSE_CAPACITY_THRESHOLD_PERCENT")
        if env_threshold:
            try:
                self.capacity_threshold_percent = float(env_threshold)
                self.logger.info(
                    f"Capacity threshold from env: {self.capacity_threshold_percent * 100:.0f}%"
                )
            except ValueError:
                self.capacity_threshold_percent = capacity_threshold_percent
                self.logger.warning(
                    f"Invalid PAUSE_CAPACITY_THRESHOLD_PERCENT, using default: {capacity_threshold_percent * 100:.0f}%"
                )
        else:
            self.capacity_threshold_percent = capacity_threshold_percent

        # Load polling interval from environment
        env_poll_interval = os.getenv("PAUSE_POLLING_INTERVAL_SECONDS", "10")
        try:
            self.polling_interval_seconds = int(env_poll_interval)
        except ValueError:
            self.polling_interval_seconds = 10
            self.logger.warning(f"Invalid PAUSE_POLLING_INTERVAL_SECONDS, using default: 10s")

        # Background polling state
        self.polling_active = False
        self._polling_task: Optional[asyncio.Task] = None

        self.logger.info(
            f"PauseManager initialized with {self.capacity_threshold_percent * 100:.0f}% threshold, "
            f"{self.polling_interval_seconds}s polling interval"
        )

    async def should_pause(self, plan_id: str) -> bool:
        """Check if work should be paused due to insufficient capacity.

        Queries all online agents and calculates available capacity.
        Returns True if ALL agents are below the capacity threshold.

        Args:
            plan_id: Plan ID for logging context

        Returns:
            bool: True if should pause (all agents < threshold), False otherwise
        """
        try:
            # Query all active agents
            agents = (
                self.db.query(AgentRegistry)
                .filter(AgentRegistry.status.in_(["online", "busy"]))
                .all()
            )

            if not agents:
                self.logger.warning(f"[{plan_id}] No online agents found, pausing work")
                return True

            # Calculate available capacity for each agent
            agent_capacities = []
            total_gpu_vram = 0.0
            total_cpu_cores = 0.0
            agent_count = 0

            for agent in agents:
                try:
                    metrics = agent.resource_metrics or {}
                    gpu_available = float(metrics.get("gpu_vram_available_gb", 0))
                    cpu_available = float(metrics.get("cpu_cores_available", 0))

                    total_gpu_vram += gpu_available
                    total_cpu_cores += cpu_available
                    agent_count += 1

                    # Calculate agent's capacity percentage (simple heuristic)
                    # Available / (available + minimal_reserved)
                    agent_cap_pct = gpu_available / max(gpu_available + 2, 1)
                    agent_capacities.append(
                        {
                            "agent_id": agent.agent_id,
                            "gpu_available_gb": gpu_available,
                            "cpu_available": cpu_available,
                            "capacity_pct": agent_cap_pct,
                        }
                    )
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Error reading metrics for agent {agent.agent_id}: {e}")
                    continue

            if not agent_capacities:
                self.logger.warning(
                    f"[{plan_id}] Could not read metrics from any agents, pausing work"
                )
                return True

            # Calculate average capacity across agents
            avg_capacity_pct = sum(a["capacity_pct"] for a in agent_capacities) / len(
                agent_capacities
            )

            # Check if all agents below threshold
            all_below_threshold = all(
                a["capacity_pct"] < self.capacity_threshold_percent for a in agent_capacities
            )

            self.logger.info(
                f"[{plan_id}] Capacity check: {agent_count} agents online, "
                f"avg capacity {avg_capacity_pct * 100:.1f}%, "
                f"GPU total {total_gpu_vram:.1f}GB, CPU total {total_cpu_cores:.1f} cores, "
                f"threshold {self.capacity_threshold_percent * 100:.0f}%, pause={all_below_threshold}"
            )

            return all_below_threshold

        except Exception as e:
            self.logger.error(f"[{plan_id}] Error in should_pause: {e}", exc_info=True)
            # Default to pausing on error (conservative approach)
            return True

    async def pause_work(
        self, plan_id: str, task_ids: List[str], work_plan_json: Optional[dict] = None
    ) -> int:
        """Pause work due to insufficient capacity.

        Creates PauseQueueEntry records for each task and persists to database.

        Args:
            plan_id: Plan ID containing tasks
            task_ids: List of task IDs to pause
            work_plan_json: Optional serialized WorkPlan (for recovery)

        Returns:
            int: Number of tasks paused
        """
        if not task_ids:
            return 0

        try:
            paused_count = 0

            for task_id in task_ids:
                try:
                    # Create pause queue entry
                    entry = PauseQueueEntry(
                        task_id=UUID(task_id) if isinstance(task_id, str) else task_id,
                        work_plan_json=work_plan_json or {"plan_id": plan_id},
                        reason="insufficient_capacity",
                        paused_at=datetime.utcnow(),
                        priority=3,  # Normal priority
                    )

                    self.db.add(entry)
                    paused_count += 1

                except Exception as e:
                    self.logger.error(f"Error pausing task {task_id}: {e}")
                    continue

            # Commit all paused entries
            try:
                self.db.commit()
                self.logger.info(
                    f"Paused {paused_count} tasks from plan {plan_id} due to capacity constraints"
                )
            except Exception as commit_err:
                self.logger.error(f"Error committing paused tasks: {commit_err}")
                self.db.rollback()
                paused_count = 0

            return paused_count

        except Exception as e:
            self.logger.error(f"Error in pause_work: {e}", exc_info=True)
            return 0

    async def resume_paused_work(self) -> int:
        """Resume paused work when capacity becomes available.

        Queries pause_queue table for entries ready to resume.
        Checks capacity and resumes if available.

        Returns:
            int: Number of tasks resumed
        """
        try:
            # Query paused entries ready for resume
            paused_entries = (
                self.db.query(PauseQueueEntry)
                .filter(
                    (PauseQueueEntry.resume_after == None)
                    | (PauseQueueEntry.resume_after <= datetime.utcnow())
                )
                .all()
            )

            if not paused_entries:
                return 0

            resumed_count = 0
            skipped_count = 0

            for entry in paused_entries:
                try:
                    # Check if capacity now available
                    should_still_pause = await self.should_pause(f"resume-{entry.id}")

                    if not should_still_pause:
                        # Capacity available, mark as resumed
                        entry.resume_after = datetime.utcnow()

                        # Update task status if needed
                        try:
                            task = self.db.query(Task).filter(Task.task_id == entry.task_id).first()
                            if task and task.status == "paused":
                                task.status = "approved"  # Reset to approved for dispatch
                        except Exception as task_err:
                            self.logger.warning(f"Could not update task status: {task_err}")

                        resumed_count += 1
                    else:
                        skipped_count += 1

                except Exception as e:
                    self.logger.warning(f"Error resuming entry {entry.id}: {e}")
                    skipped_count += 1
                    continue

            # Commit all resume updates
            if resumed_count > 0:
                try:
                    self.db.commit()
                except Exception as commit_err:
                    self.logger.error(f"Error committing resumed tasks: {commit_err}")
                    self.db.rollback()
                    resumed_count = 0

            if resumed_count > 0 or skipped_count > 0:
                self.logger.info(
                    f"Resume check: {resumed_count} resumed, {skipped_count} still waiting"
                )

            return resumed_count

        except Exception as e:
            self.logger.error(f"Error in resume_paused_work: {e}", exc_info=True)
            return 0

    async def start_resume_polling(self) -> None:
        """Start background polling task for resume cycle.

        Runs in infinite loop checking for paused work every N seconds.
        Should be called as asyncio.create_task() during orchestrator startup.

        Exits gracefully when stop_resume_polling() is called.
        """
        self.polling_active = True

        async def _resume_polling_loop():
            self.logger.info(f"Resume polling started (every {self.polling_interval_seconds}s)")
            while self.polling_active:
                try:
                    await self.resume_paused_work()
                    await asyncio.sleep(self.polling_interval_seconds)
                except asyncio.CancelledError:
                    self.logger.info("Resume polling cancelled")
                    break
                except Exception as e:
                    self.logger.error(f"Error in resume polling loop: {e}", exc_info=True)
                    # Back off on error
                    await asyncio.sleep(30)

        try:
            self._polling_task = asyncio.create_task(_resume_polling_loop())
        except Exception as e:
            self.logger.error(f"Failed to start resume polling: {e}")

    def stop_resume_polling(self) -> None:
        """Stop background polling task gracefully.

        Sets flag to stop polling loop and cancels polling task.
        Safe to call even if not polling.
        """
        try:
            self.polling_active = False

            if self._polling_task:
                self._polling_task.cancel()
                self.logger.info("Resume polling stopped")
        except Exception as e:
            self.logger.error(f"Error stopping polling: {e}")

    def __del__(self):
        """Cleanup on garbage collection."""
        try:
            self.stop_resume_polling()
        except:
            pass
