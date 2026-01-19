"""Work plan generation layer converting decomposed requests to executable plans.

Provides:
- WorkPlanner: Service for generating ordered, resource-aware task plans
- Plan generation with complexity assessment and fallback detection
- Task reordering based on resource availability
- Human-readable plan summaries for user approval
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.common.models import (
    DecomposedRequest,
    IntentToWorkTypeMapping,
    WorkPlan,
    WorkTask,
)

logger = logging.getLogger(__name__)


class WorkPlanner:
    """Service that generates executable plans from decomposed requests.

    Takes the abstract decomposed request (from RequestDecomposer) and transforms
    it into a concrete, ordered, resource-aware plan ready for user approval.

    Responsibilities:
    - Map high-level intents to executable work types
    - Create ordered task sequence with resource requirements
    - Reorder tasks based on resource availability (ready first)
    - Assess complexity and determine external AI fallback need
    - Generate human-readable plan summaries
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, logger_obj: Optional[logging.Logger] = None):
        """Initialize work planner.

        Args:
            config: Configuration dict with work type mappings (optional)
            logger_obj: Logger instance (optional, uses module logger if not provided)
        """
        self.config = config or {}
        self.logger = logger_obj or logger
        self._intent_mapping = self._get_intent_mapping()

    def _get_intent_mapping(self) -> Dict[str, IntentToWorkTypeMapping]:
        """Get mapping of known intents to work types.

        Returns:
            Dict mapping intent strings to IntentToWorkTypeMapping objects
        """
        return {
            "deploy_kuma": IntentToWorkTypeMapping(
                intent="deploy_kuma",
                work_type="deploy_service",
                agent_type="infra",
                estimated_duration_seconds=180,
                gpu_vram_mb=0,
                cpu_cores=2,
            ),
            "add_portals_to_config": IntentToWorkTypeMapping(
                intent="add_portals_to_config",
                work_type="run_playbook",
                agent_type="infra",
                estimated_duration_seconds=60,
                gpu_vram_mb=0,
                cpu_cores=1,
            ),
            "run_automation": IntentToWorkTypeMapping(
                intent="run_automation",
                work_type="run_playbook",
                agent_type="infra",
                estimated_duration_seconds=120,
                gpu_vram_mb=0,
                cpu_cores=1,
            ),
            "research": IntentToWorkTypeMapping(
                intent="research",
                work_type="research_task",
                agent_type="research",
                estimated_duration_seconds=300,
                gpu_vram_mb=0,
                cpu_cores=1,
            ),
            "code_gen": IntentToWorkTypeMapping(
                intent="code_gen",
                work_type="code_generation",
                agent_type="code",
                estimated_duration_seconds=120,
                gpu_vram_mb=2048,
                cpu_cores=2,
            ),
        }

    async def generate_plan(
        self,
        decomposed: DecomposedRequest,
        available_resources: Dict[str, int],
    ) -> WorkPlan:
        """Generate executable plan from decomposed request.

        Algorithm:
        1. Map each subtask intent to work_type/agent_type
        2. Create WorkTask for each subtask with resource requirements
        3. Check resource availability for each task
        4. Reorder tasks (ready tasks before blocked tasks)
        5. Assess complexity and fallback need
        6. Build human-readable summary
        7. Return complete WorkPlan

        Args:
            decomposed: DecomposedRequest with subtasks to plan
            available_resources: Dict with gpu_vram_mb and cpu_cores available

        Returns:
            WorkPlan with ordered tasks ready for execution

        Raises:
            ValueError: If plan generation fails
        """
        try:
            plan_id = str(uuid4())

            # Handle empty request
            if not decomposed.subtasks:
                self.logger.warning(f"Decomposed request {decomposed.request_id} has no subtasks")
                return WorkPlan(
                    plan_id=plan_id,
                    request_id=decomposed.request_id,
                    tasks=[],
                    estimated_duration_seconds=0,
                    complexity_level="simple",
                    will_use_external_ai=False,
                    human_readable_summary="No tasks to execute.",
                )

            # Create tasks from subtasks
            tasks: List[WorkTask] = []
            total_duration = 0
            work_types_used: List[str] = []

            for subtask in decomposed.subtasks:
                # Get mapping for this intent
                mapping = self._intent_mapping.get(
                    subtask.intent,
                    IntentToWorkTypeMapping(
                        intent=subtask.intent,
                        work_type="custom_work",
                        agent_type="research",
                        estimated_duration_seconds=300,
                        gpu_vram_mb=0,
                        cpu_cores=1,
                    ),
                )

                # Create task
                task = WorkTask(
                    order=len(tasks) + 1,
                    name=subtask.name,
                    work_type=mapping.work_type,
                    agent_type=mapping.agent_type,
                    parameters=subtask.parameters or {},
                    resource_requirements={
                        "estimated_duration_seconds": mapping.estimated_duration_seconds,
                        "gpu_vram_mb": mapping.gpu_vram_mb,
                        "cpu_cores": mapping.cpu_cores,
                    },
                    alternatives=mapping.alternatives,
                    estimated_external_ai_calls=1 if mapping.agent_type in ["research", "code"] else 0,
                )

                tasks.append(task)
                total_duration += mapping.estimated_duration_seconds
                work_types_used.append(mapping.work_type)

            # Reorder tasks based on resource availability
            tasks = self._reorder_by_resources(tasks, available_resources)

            # Assess complexity
            complexity = self._assess_complexity(work_types_used)

            # Determine if external AI will be used
            will_use_external_ai = any(t.estimated_external_ai_calls > 0 for t in tasks) or complexity == "complex"

            # Build human-readable summary
            human_summary = self._build_human_readable_summary(tasks)

            # Create plan
            plan = WorkPlan(
                plan_id=plan_id,
                request_id=decomposed.request_id,
                tasks=tasks,
                estimated_duration_seconds=total_duration,
                complexity_level=complexity,
                will_use_external_ai=will_use_external_ai,
                human_readable_summary=human_summary,
            )

            self.logger.info(
                f"Generated plan {plan_id} with {len(tasks)} tasks, complexity={complexity}, "
                f"will_use_external_ai={will_use_external_ai}"
            )

            return plan

        except Exception as e:
            self.logger.error(f"Failed to generate plan: {e}", exc_info=True)
            raise ValueError(f"Plan generation failed: {e}") from e

    def _reorder_by_resources(
        self,
        tasks: List[WorkTask],
        available_resources: Dict[str, int],
    ) -> List[WorkTask]:
        """Reorder tasks by resource availability.

        Ready tasks (with available resources) are placed first.
        Blocked tasks (requiring unavailable resources) are placed after.

        Args:
            tasks: List of tasks to reorder
            available_resources: Available gpu_vram_mb and cpu_cores

        Returns:
            Reordered task list with updated task orders
        """
        ready = []
        blocked = []

        for task in tasks:
            if self._check_resource_availability(task, available_resources):
                ready.append(task)
            else:
                blocked.append(task)

        # Combine: ready first, then blocked
        reordered = ready + blocked

        # Re-number task orders
        for i, task in enumerate(reordered, start=1):
            task.order = i

        if blocked:
            self.logger.warning(
                f"Reordered {len(ready)} ready tasks before {len(blocked)} blocked tasks"
            )
        else:
            self.logger.info(f"All {len(ready)} tasks have available resources")

        return reordered

    def _assess_complexity(self, work_types: List[str]) -> str:
        """Assess plan complexity based on work types.

        Args:
            work_types: List of work types in the plan

        Returns:
            Complexity level: "simple", "medium", or "complex"
        """
        # Complex: research or code generation tasks
        if any(wt in ["research_task", "code_generation", "architecture_review"] for wt in work_types):
            return "complex"

        # Medium: more than 3 tasks
        if len(work_types) > 3:
            return "medium"

        # Simple: 1-3 simple tasks
        return "simple"

    def _build_human_readable_summary(self, tasks: List[WorkTask]) -> str:
        """Build human-readable plan summary.

        Format: numbered list with task names and durations, plus total time.

        Args:
            tasks: List of ordered tasks

        Returns:
            Plain text summary
        """
        if not tasks:
            return "No tasks to execute."

        lines = []

        # Build task list
        for task in tasks:
            duration_sec = task.resource_requirements.get("estimated_duration_seconds", 0)
            duration_min = duration_sec / 60

            if duration_min >= 1:
                duration_str = f"~{int(duration_min)} minute" if duration_min == 1 else f"~{int(duration_min)} minutes"
            else:
                duration_str = f"{duration_sec} seconds"

            lines.append(f"{task.order}. {task.name} (estimated {duration_str})")

        # Add total time
        total_sec = sum(t.resource_requirements.get("estimated_duration_seconds", 0) for t in tasks)
        total_min = total_sec / 60

        if total_min >= 1:
            total_str = f"~{int(total_min)} minute" if total_min == 1 else f"~{int(total_min)} minutes"
        else:
            total_str = f"{total_sec} seconds"

        lines.append(f"\nTotal estimated time: {total_str}")

        # Add resource warnings if any high-resource tasks
        high_resource_tasks = [t for t in tasks if t.resource_requirements.get("gpu_vram_mb", 0) > 4000]
        if high_resource_tasks:
            lines.append("\nNote: This plan includes high-resource tasks requiring GPU access.")

        return "\n".join(lines)

    def _check_resource_availability(
        self,
        task: WorkTask,
        available: Dict[str, int],
    ) -> bool:
        """Check if available resources satisfy task requirements.

        Args:
            task: Task to check
            available: Available resources dict

        Returns:
            True if resources available, False otherwise
        """
        required_gpu = task.resource_requirements.get("gpu_vram_mb", 0)
        required_cpu = task.resource_requirements.get("cpu_cores", 0)

        available_gpu = available.get("gpu_vram_mb", 0)
        available_cpu = available.get("cpu_cores", 0)

        # Task is "ready" if it doesn't require unavailable resources
        # GPU tasks are "ready" if GPU available or if task doesn't require GPU
        # CPU-only tasks are always "ready"
        if required_gpu > 0:
            return available_gpu >= required_gpu
        else:
            return available_cpu >= required_cpu
