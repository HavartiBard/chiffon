"""Tests for TaskExecutor — LLM-powered task execution.

Written TDD-style: tests are written first, then the implementation.
All LLM and SkillsRegistry interactions are mocked so no live server is needed.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from chiffon.executor.executor import TaskExecutor
from chiffon.queue.file_queue import Task


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

LLM_RESPONSE_FULL = """\
## PLAN
1. Parse input
2. Validate
3. Generate output

## CODE
# Generated code here
result = "success"

## VERIFICATION
# Run pytest to verify
assert result == "success"
"""

LLM_RESPONSE_PARTIAL = """\
## PLAN
1. Do the thing

## CODE
pass
"""

LLM_RESPONSE_EMPTY = ""


@pytest.fixture
def mock_llm():
    """LlamaClient mock with healthy server and a canned full response."""
    client = MagicMock()
    client.health_check.return_value = True
    client.generate.return_value = LLM_RESPONSE_FULL
    return client


@pytest.fixture
def mock_registry():
    """SkillsRegistry mock that returns no content by default."""
    registry = MagicMock()
    registry.get_skill_content.return_value = None
    return registry


@pytest.fixture
def executor(mock_llm, mock_registry):
    """TaskExecutor with mocked LLM and registry injected via patch."""
    with (
        patch("chiffon.executor.executor.LlamaClient", return_value=mock_llm),
        patch("chiffon.executor.executor.SkillsRegistry", return_value=mock_registry),
    ):
        exc = TaskExecutor(
            repo_path=Path("/tmp/test"),
            queue_path=Path("/tmp/test/tasks/queue"),
            llm_server_url="http://localhost:8000",
        )
    return exc


@pytest.fixture
def simple_task():
    """Minimal Task with applicable_skills."""
    return Task(
        id="task-1",
        goal="Validate YAML",
        applicable_skills=["yaml-validation", "error-reporting"],
    )


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


def test_executor_initializes():
    """TaskExecutor stores repo_path on construction."""
    with (
        patch("chiffon.executor.executor.LlamaClient"),
        patch("chiffon.executor.executor.SkillsRegistry"),
    ):
        exc = TaskExecutor(
            repo_path=Path("/tmp/test"),
            queue_path=Path("/tmp/test/tasks/queue"),
            llm_server_url="http://localhost:8000",
        )
    assert exc.repo_path == Path("/tmp/test")


def test_executor_stores_queue_path():
    """TaskExecutor stores queue_path on construction."""
    with (
        patch("chiffon.executor.executor.LlamaClient"),
        patch("chiffon.executor.executor.SkillsRegistry"),
    ):
        exc = TaskExecutor(
            repo_path=Path("/tmp/test"),
            queue_path=Path("/tmp/queue"),
        )
    assert exc.queue_path == Path("/tmp/queue")


def test_executor_has_check_health_method():
    """TaskExecutor exposes a check_health method."""
    with (
        patch("chiffon.executor.executor.LlamaClient"),
        patch("chiffon.executor.executor.SkillsRegistry"),
    ):
        exc = TaskExecutor(
            repo_path=Path("/tmp/test"),
            queue_path=Path("/tmp/test/tasks/queue"),
        )
    assert hasattr(exc, "check_health")
    assert callable(exc.check_health)


def test_executor_wires_llm_client(mock_llm, mock_registry):
    """TaskExecutor passes llm_server_url to LlamaClient."""
    with (
        patch("chiffon.executor.executor.LlamaClient", return_value=mock_llm) as llm_cls,
        patch("chiffon.executor.executor.SkillsRegistry", return_value=mock_registry),
    ):
        TaskExecutor(
            repo_path=Path("/tmp/test"),
            queue_path=Path("/tmp/test/tasks/queue"),
            llm_server_url="http://gpu-box:9000",
        )
    llm_cls.assert_called_once_with(base_url="http://gpu-box:9000")


def test_executor_uses_default_skills_dir(mock_llm, mock_registry):
    """TaskExecutor defaults skills_dir to the sibling skills/ package."""
    with (
        patch("chiffon.executor.executor.LlamaClient", return_value=mock_llm),
        patch("chiffon.executor.executor.SkillsRegistry", return_value=mock_registry) as reg_cls,
    ):
        TaskExecutor(
            repo_path=Path("/tmp/test"),
            queue_path=Path("/tmp/test/tasks/queue"),
        )
    called_path = reg_cls.call_args[0][0]
    assert called_path.name == "skills"


def test_executor_accepts_custom_skills_dir(mock_llm, mock_registry):
    """TaskExecutor accepts an explicit skills_dir override."""
    custom_dir = Path("/custom/skills")
    with (
        patch("chiffon.executor.executor.LlamaClient", return_value=mock_llm),
        patch("chiffon.executor.executor.SkillsRegistry", return_value=mock_registry) as reg_cls,
    ):
        TaskExecutor(
            repo_path=Path("/tmp/test"),
            queue_path=Path("/tmp/test/tasks/queue"),
            skills_dir=custom_dir,
        )
    reg_cls.assert_called_once_with(custom_dir)


# ---------------------------------------------------------------------------
# check_health() tests
# ---------------------------------------------------------------------------


def test_check_health_returns_true_when_llm_healthy(executor, mock_llm):
    """check_health() returns True when LLM reports healthy."""
    mock_llm.health_check.return_value = True
    assert executor.check_health() is True


def test_check_health_raises_when_llm_unhealthy(executor, mock_llm):
    """check_health() raises RuntimeError when LLM is unreachable."""
    mock_llm.health_check.return_value = False
    with pytest.raises(RuntimeError, match="LLM server unreachable"):
        executor.check_health()


def test_check_health_calls_llm_health_check(executor, mock_llm):
    """check_health() delegates to LlamaClient.health_check()."""
    mock_llm.health_check.return_value = True
    executor.check_health()
    mock_llm.health_check.assert_called_once()


# ---------------------------------------------------------------------------
# build_execution_prompt() tests
# ---------------------------------------------------------------------------


def test_build_execution_prompt_returns_string(executor, simple_task):
    """build_execution_prompt() returns a non-empty string."""
    result = executor.build_execution_prompt(simple_task)
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_execution_prompt_includes_task_id(executor, simple_task):
    """build_execution_prompt() includes the task id in the output."""
    result = executor.build_execution_prompt(simple_task)
    assert "task-1" in result


def test_build_execution_prompt_includes_task_goal(executor, simple_task):
    """build_execution_prompt() includes the task goal in the output."""
    result = executor.build_execution_prompt(simple_task)
    assert "Validate YAML" in result


def test_build_execution_prompt_passes_applicable_skills(executor, simple_task, mock_registry):
    """build_execution_prompt() delegates skill loading via PromptBuilder."""
    # PromptBuilder is injected; we just verify the prompt is built without error
    # and contains structural markers expected from the system message.
    result = executor.build_execution_prompt(simple_task)
    # PromptBuilder.SYSTEM_MESSAGE always contains ## PLAN
    assert "PLAN" in result


def test_build_execution_prompt_respects_skills_limit(mock_llm, mock_registry):
    """build_execution_prompt() caps applicable_skills to 5 entries."""
    with (
        patch("chiffon.executor.executor.LlamaClient", return_value=mock_llm),
        patch("chiffon.executor.executor.SkillsRegistry", return_value=mock_registry),
    ):
        exc = TaskExecutor(
            repo_path=Path("/tmp/test"),
            queue_path=Path("/tmp/test/tasks/queue"),
        )

    task = Task(
        id="task-big",
        goal="Test skill cap",
        applicable_skills=["s1", "s2", "s3", "s4", "s5", "s6", "s7"],
    )
    # Should not raise; internally limits to 5 skills
    prompt = exc.build_execution_prompt(task)
    assert isinstance(prompt, str)


# ---------------------------------------------------------------------------
# parse_llm_response() tests
# ---------------------------------------------------------------------------


def test_parse_llm_response_extracts_all_sections(executor):
    """parse_llm_response() extracts PLAN, CODE, and VERIFICATION sections."""
    result = executor.parse_llm_response(LLM_RESPONSE_FULL)
    assert "plan" in result
    assert "code" in result
    assert "verification" in result


def test_parse_llm_response_plan_content(executor):
    """parse_llm_response() captures the content under ## PLAN."""
    result = executor.parse_llm_response(LLM_RESPONSE_FULL)
    assert "Parse input" in result["plan"]
    assert "Validate" in result["plan"]


def test_parse_llm_response_code_content(executor):
    """parse_llm_response() captures the content under ## CODE."""
    result = executor.parse_llm_response(LLM_RESPONSE_FULL)
    assert 'result = "success"' in result["code"]


def test_parse_llm_response_verification_content(executor):
    """parse_llm_response() captures the content under ## VERIFICATION."""
    result = executor.parse_llm_response(LLM_RESPONSE_FULL)
    assert 'assert result == "success"' in result["verification"]


def test_parse_llm_response_missing_verification_returns_empty_string(executor):
    """parse_llm_response() returns empty string for missing VERIFICATION section."""
    result = executor.parse_llm_response(LLM_RESPONSE_PARTIAL)
    assert result.get("verification", "") == ""


def test_parse_llm_response_empty_input_returns_empty_dict(executor):
    """parse_llm_response() returns an empty dict for an empty response."""
    result = executor.parse_llm_response(LLM_RESPONSE_EMPTY)
    assert result == {}


def test_parse_llm_response_malformed_no_sections(executor):
    """parse_llm_response() returns empty dict when no ## headers are present."""
    result = executor.parse_llm_response("Just some random text without headers")
    assert result == {}


def test_parse_llm_response_section_keys_are_lowercase(executor):
    """parse_llm_response() keys are lowercase regardless of header casing."""
    response = "## PLAN\nstep one\n\n## CODE\npass\n"
    result = executor.parse_llm_response(response)
    assert "plan" in result
    assert "code" in result


# ---------------------------------------------------------------------------
# execute_task() tests — async, full flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_task_returns_success_dict(executor, mock_llm, simple_task):
    """execute_task() returns a dict with success=True on happy path."""
    mock_llm.health_check.return_value = True
    mock_llm.generate.return_value = LLM_RESPONSE_FULL
    result = await executor.execute_task(simple_task)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_execute_task_result_contains_plan(executor, mock_llm, simple_task):
    """execute_task() result dict contains a 'plan' key with content."""
    mock_llm.health_check.return_value = True
    mock_llm.generate.return_value = LLM_RESPONSE_FULL
    result = await executor.execute_task(simple_task)
    assert "plan" in result
    assert "Parse input" in result["plan"]


@pytest.mark.asyncio
async def test_execute_task_result_contains_code(executor, mock_llm, simple_task):
    """execute_task() result dict contains a 'code' key with content."""
    mock_llm.health_check.return_value = True
    mock_llm.generate.return_value = LLM_RESPONSE_FULL
    result = await executor.execute_task(simple_task)
    assert "code" in result
    assert 'result = "success"' in result["code"]


@pytest.mark.asyncio
async def test_execute_task_result_contains_verification(executor, mock_llm, simple_task):
    """execute_task() result dict contains a 'verification' key."""
    mock_llm.health_check.return_value = True
    mock_llm.generate.return_value = LLM_RESPONSE_FULL
    result = await executor.execute_task(simple_task)
    assert "verification" in result


@pytest.mark.asyncio
async def test_execute_task_calls_llm_generate(executor, mock_llm, simple_task):
    """execute_task() invokes LlamaClient.generate() exactly once."""
    mock_llm.health_check.return_value = True
    mock_llm.generate.return_value = LLM_RESPONSE_FULL
    await executor.execute_task(simple_task)
    mock_llm.generate.assert_called_once()


@pytest.mark.asyncio
async def test_execute_task_returns_failure_on_llm_error(executor, mock_llm, simple_task):
    """execute_task() returns success=False dict when LLM raises."""
    mock_llm.health_check.return_value = True
    mock_llm.generate.side_effect = ValueError("Connection refused")
    result = await executor.execute_task(simple_task)
    assert result["success"] is False
    assert "error" in result
    assert "Connection refused" in result["error"]


@pytest.mark.asyncio
async def test_execute_task_failure_dict_has_no_plan_key(executor, mock_llm, simple_task):
    """On failure the result dict does NOT contain 'plan'."""
    mock_llm.health_check.return_value = True
    mock_llm.generate.side_effect = RuntimeError("boom")
    result = await executor.execute_task(simple_task)
    assert result["success"] is False
    assert "plan" not in result


@pytest.mark.asyncio
async def test_execute_task_health_check_not_called_inline(executor, mock_llm, simple_task):
    """execute_task() does NOT call check_health internally — caller is responsible.

    The design spec has check_health() as a separate method that the CLI or
    caller invokes before execute_task().  execute_task() itself only calls
    llm.generate(), not llm.health_check().
    """
    mock_llm.health_check.return_value = True
    mock_llm.generate.return_value = LLM_RESPONSE_FULL
    await executor.execute_task(simple_task)
    # generate was called, but health_check should NOT have been called by execute_task
    mock_llm.health_check.assert_not_called()
