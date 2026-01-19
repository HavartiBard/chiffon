"""Comprehensive tests for WorkPlanner service.

Tests cover:
- Plan generation from decomposed requests
- Resource ordering and availability checking
- Complexity assessment
- Intent mapping to work types
- Plan validation and error handling
"""

import logging
from uuid import uuid4

import pytest

from src.common.models import (
    DecomposedRequest,
    Subtask,
    WorkTask,
)
from src.orchestrator.planner import WorkPlanner


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def planner():
    """Create a WorkPlanner instance for testing."""
    return WorkPlanner(logger_obj=logging.getLogger("test"))


@pytest.fixture
def simple_decomposed_request():
    """Simple request with single deploy task."""
    return DecomposedRequest(
        request_id=str(uuid4()),
        original_request="Deploy Kuma",
        subtasks=[
            Subtask(
                order=1,
                name="Deploy Kuma Uptime",
                intent="deploy_kuma",
                confidence=0.95,
            )
        ],
        ambiguities=[],
        out_of_scope=[],
        complexity_level="simple",
        decomposer_model="claude",
    )


@pytest.fixture
def complex_decomposed_request():
    """Complex request with multiple subtasks including research."""
    return DecomposedRequest(
        request_id=str(uuid4()),
        original_request="Deploy Kuma and research integration points",
        subtasks=[
            Subtask(
                order=1,
                name="Deploy Kuma Uptime",
                intent="deploy_kuma",
                confidence=0.95,
            ),
            Subtask(
                order=2,
                name="Add portals to config",
                intent="add_portals_to_config",
                confidence=0.88,
            ),
            Subtask(
                order=3,
                name="Research integration points",
                intent="research",
                confidence=0.75,
            ),
        ],
        ambiguities=[],
        out_of_scope=[],
        complexity_level="medium",
        decomposer_model="claude",
    )


@pytest.fixture
def available_resources_full():
    """Full resource availability."""
    return {"gpu_vram_mb": 8000, "cpu_cores": 8}


@pytest.fixture
def available_resources_cpu_only():
    """CPU-only resources (no GPU)."""
    return {"gpu_vram_mb": 0, "cpu_cores": 4}


@pytest.fixture
def available_resources_minimal():
    """Minimal resource availability."""
    return {"gpu_vram_mb": 0, "cpu_cores": 1}


# ============================================================================
# TEST CLASS 1: TestPlanGeneration
# ============================================================================


class TestPlanGeneration:
    """Test basic plan generation from decomposed requests."""

    @pytest.mark.asyncio
    async def test_generate_plan_simple_request(self, planner, simple_decomposed_request, available_resources_full):
        """Test generating plan from simple single-task request."""
        plan = await planner.generate_plan(simple_decomposed_request, available_resources_full)

        assert plan.plan_id
        assert len(plan.tasks) == 1
        assert plan.tasks[0].name == "Deploy Kuma Uptime"
        assert plan.status == "pending_approval"
        assert plan.complexity_level == "simple"

    @pytest.mark.asyncio
    async def test_generate_plan_complex_request(self, planner, complex_decomposed_request, available_resources_full):
        """Test generating plan from complex multi-task request."""
        plan = await planner.generate_plan(complex_decomposed_request, available_resources_full)

        assert plan.plan_id
        assert len(plan.tasks) == 3
        assert plan.tasks[0].name == "Deploy Kuma Uptime"
        assert plan.tasks[1].name == "Add portals to config"
        assert plan.tasks[2].name == "Research integration points"

    @pytest.mark.asyncio
    async def test_plan_status_pending_approval(self, planner, simple_decomposed_request, available_resources_full):
        """Test that new plans have status='pending_approval'."""
        plan = await planner.generate_plan(simple_decomposed_request, available_resources_full)

        assert plan.status == "pending_approval"
        assert plan.approved_at is None

    @pytest.mark.asyncio
    async def test_plan_includes_human_summary(self, planner, simple_decomposed_request, available_resources_full):
        """Test that plan includes readable human_readable_summary."""
        plan = await planner.generate_plan(simple_decomposed_request, available_resources_full)

        assert plan.human_readable_summary
        assert "Deploy Kuma" in plan.human_readable_summary
        assert "estimated" in plan.human_readable_summary.lower()
        assert "Total estimated time" in plan.human_readable_summary

    @pytest.mark.asyncio
    async def test_estimated_duration_correct(self, planner, simple_decomposed_request, available_resources_full):
        """Test that total duration = sum of task durations."""
        plan = await planner.generate_plan(simple_decomposed_request, available_resources_full)

        # Deploy Kuma is 180 seconds
        assert plan.estimated_duration_seconds == 180

    @pytest.mark.asyncio
    async def test_estimated_duration_multi_task(self, planner, complex_decomposed_request, available_resources_full):
        """Test duration calculation for multi-task plan."""
        plan = await planner.generate_plan(complex_decomposed_request, available_resources_full)

        # 180 (deploy) + 60 (add portals) + 300 (research) = 540
        assert plan.estimated_duration_seconds == 540


# ============================================================================
# TEST CLASS 2: TestResourceOrdering
# ============================================================================


class TestResourceOrdering:
    """Test resource-aware task ordering."""

    @pytest.mark.asyncio
    async def test_ready_tasks_before_blocked(self, planner, available_resources_cpu_only):
        """Test that tasks with available resources come before blocked tasks."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Test resource ordering",
            subtasks=[
                Subtask(
                    order=1,
                    name="GPU task",
                    intent="code_gen",  # Requires GPU
                    confidence=0.95,
                ),
                Subtask(
                    order=2,
                    name="CPU task",
                    intent="deploy_kuma",  # CPU-only
                    confidence=0.95,
                ),
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="simple",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_cpu_only)

        # CPU task should come first (order 1), GPU task should be blocked (order 2)
        assert plan.tasks[0].name == "CPU task"
        assert plan.tasks[0].order == 1
        assert plan.tasks[1].name == "GPU task"
        assert plan.tasks[1].order == 2

    @pytest.mark.asyncio
    async def test_blocked_tasks_ordered(self, planner, available_resources_cpu_only):
        """Test that blocked tasks are ordered after ready tasks."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Test blocking",
            subtasks=[
                Subtask(
                    order=1,
                    name="First CPU",
                    intent="deploy_kuma",
                    confidence=0.95,
                ),
                Subtask(
                    order=2,
                    name="GPU task",
                    intent="code_gen",
                    confidence=0.95,
                ),
                Subtask(
                    order=3,
                    name="Second CPU",
                    intent="add_portals_to_config",
                    confidence=0.95,
                ),
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="simple",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_cpu_only)

        # Both CPU tasks should come before GPU task
        cpu_tasks = [t for t in plan.tasks if "CPU" in t.name]
        gpu_tasks = [t for t in plan.tasks if "GPU" in t.name]

        assert len(cpu_tasks) == 2
        assert len(gpu_tasks) == 1
        assert all(t.order < gpu_tasks[0].order for t in cpu_tasks)

    @pytest.mark.asyncio
    async def test_all_gpu_tasks_blocked(self, planner, available_resources_cpu_only):
        """Test when all GPU-intensive tasks are blocked."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="GPU-only plan",
            subtasks=[
                Subtask(
                    order=1,
                    name="Code generation",
                    intent="code_gen",
                    confidence=0.95,
                )
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="simple",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_cpu_only)

        # GPU task should be in blocked section but still in plan
        assert len(plan.tasks) == 1
        assert plan.tasks[0].name == "Code generation"


# ============================================================================
# TEST CLASS 3: TestComplexityAssessment
# ============================================================================


class TestComplexityAssessment:
    """Test plan complexity assessment."""

    @pytest.mark.asyncio
    async def test_simple_plan(self, planner, simple_decomposed_request, available_resources_full):
        """Test that 1-2 simple tasks = 'simple' complexity."""
        plan = await planner.generate_plan(simple_decomposed_request, available_resources_full)

        assert plan.complexity_level == "simple"

    @pytest.mark.asyncio
    async def test_medium_plan(self, planner, available_resources_full):
        """Test that >3 tasks = 'medium' complexity."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Four-task plan",
            subtasks=[
                Subtask(order=1, name="Task 1", intent="deploy_kuma", confidence=0.95),
                Subtask(order=2, name="Task 2", intent="add_portals_to_config", confidence=0.95),
                Subtask(order=3, name="Task 3", intent="run_automation", confidence=0.95),
                Subtask(order=4, name="Task 4", intent="deploy_kuma", confidence=0.95),
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="medium",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_full)

        assert plan.complexity_level == "medium"

    @pytest.mark.asyncio
    async def test_complex_plan_with_research(self, planner, complex_decomposed_request, available_resources_full):
        """Test that research tasks = 'complex' complexity."""
        plan = await planner.generate_plan(complex_decomposed_request, available_resources_full)

        assert plan.complexity_level == "complex"

    @pytest.mark.asyncio
    async def test_complex_plan_with_code_gen(self, planner, available_resources_full):
        """Test that code generation tasks = 'complex' complexity."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Code generation plan",
            subtasks=[
                Subtask(order=1, name="Generate code", intent="code_gen", confidence=0.95),
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="complex",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_full)

        assert plan.complexity_level == "complex"

    @pytest.mark.asyncio
    async def test_will_use_external_ai_flag(self, planner, complex_decomposed_request, available_resources_full):
        """Test that complex plans have will_use_external_ai=True."""
        plan = await planner.generate_plan(complex_decomposed_request, available_resources_full)

        # Complex plan with research task should need external AI
        assert plan.will_use_external_ai is True

    @pytest.mark.asyncio
    async def test_simple_plan_no_external_ai(self, planner, simple_decomposed_request, available_resources_full):
        """Test that simple plans have will_use_external_ai=False."""
        plan = await planner.generate_plan(simple_decomposed_request, available_resources_full)

        assert plan.will_use_external_ai is False


# ============================================================================
# TEST CLASS 4: TestIntentMapping
# ============================================================================


class TestIntentMapping:
    """Test intent to work type mapping."""

    @pytest.mark.asyncio
    async def test_deploy_kuma_maps_to_infra(self, planner, simple_decomposed_request, available_resources_full):
        """Test that 'deploy_kuma' intent maps to infra agent with deploy_service work type."""
        plan = await planner.generate_plan(simple_decomposed_request, available_resources_full)

        task = plan.tasks[0]
        assert task.work_type == "deploy_service"
        assert task.agent_type == "infra"

    @pytest.mark.asyncio
    async def test_add_portals_maps_to_infra(self, planner, available_resources_full):
        """Test that 'add_portals_to_config' intent maps to infra agent."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Add portals",
            subtasks=[
                Subtask(
                    order=1,
                    name="Add portals",
                    intent="add_portals_to_config",
                    confidence=0.95,
                )
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="simple",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_full)

        task = plan.tasks[0]
        assert task.work_type == "run_playbook"
        assert task.agent_type == "infra"

    @pytest.mark.asyncio
    async def test_research_intent_maps_to_research(self, planner, available_resources_full):
        """Test that 'research' intent maps to research agent."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Research something",
            subtasks=[
                Subtask(
                    order=1,
                    name="Research",
                    intent="research",
                    confidence=0.95,
                )
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="complex",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_full)

        task = plan.tasks[0]
        assert task.work_type == "research_task"
        assert task.agent_type == "research"

    @pytest.mark.asyncio
    async def test_code_gen_intent_maps_to_code(self, planner, available_resources_full):
        """Test that 'code_gen' intent maps to code agent."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Generate code",
            subtasks=[
                Subtask(
                    order=1,
                    name="Generate code",
                    intent="code_gen",
                    confidence=0.95,
                )
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="complex",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_full)

        task = plan.tasks[0]
        assert task.work_type == "code_generation"
        assert task.agent_type == "code"

    @pytest.mark.asyncio
    async def test_unknown_intent_defaults_to_research(self, planner, available_resources_full):
        """Test that unknown intents default to research agent with custom_work."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Unknown task",
            subtasks=[
                Subtask(
                    order=1,
                    name="Unknown task",
                    intent="unknown_intent",
                    confidence=0.95,
                )
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="simple",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_full)

        task = plan.tasks[0]
        assert task.work_type == "custom_work"
        assert task.agent_type == "research"


# ============================================================================
# TEST CLASS 5: TestPlanValidation
# ============================================================================


class TestPlanValidation:
    """Test plan validation and structure."""

    @pytest.mark.asyncio
    async def test_plan_has_valid_uuid(self, planner, simple_decomposed_request, available_resources_full):
        """Test that plan_id and request_id are valid UUIDs."""
        plan = await planner.generate_plan(simple_decomposed_request, available_resources_full)

        # Should be able to parse as UUID
        assert len(plan.plan_id) == 36  # UUID string length
        assert "-" in plan.plan_id

    @pytest.mark.asyncio
    async def test_all_tasks_have_resources(self, planner, complex_decomposed_request, available_resources_full):
        """Test that every task has resource_requirements with required keys."""
        plan = await planner.generate_plan(complex_decomposed_request, available_resources_full)

        for task in plan.tasks:
            assert task.resource_requirements
            assert "estimated_duration_seconds" in task.resource_requirements
            assert "gpu_vram_mb" in task.resource_requirements
            assert "cpu_cores" in task.resource_requirements

    @pytest.mark.asyncio
    async def test_task_orders_sequential(self, planner, complex_decomposed_request, available_resources_full):
        """Test that task orders are 1, 2, 3, ... with no gaps."""
        plan = await planner.generate_plan(complex_decomposed_request, available_resources_full)

        orders = [t.order for t in plan.tasks]
        expected = list(range(1, len(plan.tasks) + 1))

        assert orders == expected

    @pytest.mark.asyncio
    async def test_task_orders_positive(self, planner, complex_decomposed_request, available_resources_full):
        """Test that all task orders are positive integers."""
        plan = await planner.generate_plan(complex_decomposed_request, available_resources_full)

        for task in plan.tasks:
            assert task.order > 0
            assert isinstance(task.order, int)


# ============================================================================
# TEST CLASS 6: TestErrorHandling
# ============================================================================


class TestErrorHandling:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_empty_decomposed_request(self, planner, available_resources_full):
        """Test that empty subtasks are handled gracefully."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Empty request",
            subtasks=[],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="simple",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_full)

        assert len(plan.tasks) == 0
        assert plan.estimated_duration_seconds == 0
        assert "No tasks" in plan.human_readable_summary

    @pytest.mark.asyncio
    async def test_no_resources_available(self, planner, complex_decomposed_request):
        """Test plan generation when no resources available."""
        available = {"gpu_vram_mb": 0, "cpu_cores": 0}

        plan = await planner.generate_plan(complex_decomposed_request, available)

        # Should still generate plan, but tasks reordered
        assert len(plan.tasks) > 0

    @pytest.mark.asyncio
    async def test_malformed_intent(self, planner, available_resources_full):
        """Test that malformed intent defaults to custom_work."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Malformed",
            subtasks=[
                Subtask(
                    order=1,
                    name="Bad task",
                    intent="not_a_real_intent",
                    confidence=0.95,
                )
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="simple",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_full)

        task = plan.tasks[0]
        assert task.work_type == "custom_work"

    @pytest.mark.asyncio
    async def test_missing_resources_dict(self, planner, simple_decomposed_request):
        """Test generate_plan without available_resources (empty dict)."""
        plan = await planner.generate_plan(simple_decomposed_request, {})

        # Should handle gracefully, likely treating all tasks as blocked
        assert len(plan.tasks) > 0

    @pytest.mark.asyncio
    async def test_external_ai_calls_tracked(self, planner, complex_decomposed_request, available_resources_full):
        """Test that estimated_external_ai_calls is tracked in tasks."""
        plan = await planner.generate_plan(complex_decomposed_request, available_resources_full)

        # Research task should have estimated_external_ai_calls > 0
        research_tasks = [t for t in plan.tasks if t.agent_type == "research"]
        assert len(research_tasks) > 0
        assert any(t.estimated_external_ai_calls > 0 for t in research_tasks)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestIntegration:
    """Integration tests for end-to-end planner behavior."""

    @pytest.mark.asyncio
    async def test_kuma_deployment_scenario(self, planner, available_resources_full):
        """Test realistic Kuma deployment scenario from CONTEXT."""
        decomposed = DecomposedRequest(
            request_id=str(uuid4()),
            original_request="Deploy Kuma Uptime to homelab and add existing portals to config",
            subtasks=[
                Subtask(
                    order=1,
                    name="Deploy Kuma Uptime",
                    intent="deploy_kuma",
                    confidence=0.95,
                ),
                Subtask(
                    order=2,
                    name="Add existing portals to configuration",
                    intent="add_portals_to_config",
                    confidence=0.88,
                ),
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="simple",
            decomposer_model="claude",
        )

        plan = await planner.generate_plan(decomposed, available_resources_full)

        # Verify plan structure
        assert plan.plan_id
        assert len(plan.tasks) == 2
        assert plan.complexity_level == "simple"
        assert not plan.will_use_external_ai  # Simple deployment doesn't need Claude

        # Verify task ordering
        assert plan.tasks[0].name == "Deploy Kuma Uptime"
        assert plan.tasks[1].name == "Add existing portals to configuration"

        # Verify human summary is clear and concise
        assert "1. Deploy Kuma" in plan.human_readable_summary
        assert "2. Add existing portals" in plan.human_readable_summary
        assert "Total estimated time" in plan.human_readable_summary

    @pytest.mark.asyncio
    async def test_plan_summary_is_readable(self, planner, complex_decomposed_request, available_resources_full):
        """Test that plan summary is human-readable and <1 minute to understand."""
        plan = await planner.generate_plan(complex_decomposed_request, available_resources_full)

        # Summary should be brief (< 500 chars for quick reading)
        assert len(plan.human_readable_summary) < 500

        # Should have numbered tasks
        assert "1." in plan.human_readable_summary
        assert "2." in plan.human_readable_summary

        # Should have time estimates
        assert any(unit in plan.human_readable_summary for unit in ["minute", "second"])
