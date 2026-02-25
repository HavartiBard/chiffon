"""Tests for PromptBuilder — written before implementation (TDD)."""

import pytest
from pathlib import Path
from chiffon.executor.prompt_builder import PromptBuilder
from chiffon.skills.registry import SkillsRegistry


@pytest.fixture
def registry():
    return SkillsRegistry(Path(__file__).parent.parent / "src" / "chiffon" / "skills")


@pytest.fixture
def builder(registry):
    return PromptBuilder(registry)


def test_builds_prompt_with_task():
    """Test that prompt builder includes task YAML."""
    builder = PromptBuilder(
        SkillsRegistry(
            Path(__file__).parent.parent / "src" / "chiffon" / "skills"
        )
    )

    task_yaml = """
id: task-1
goal: Validate task YAML
description: Ensure all tasks have required fields
"""

    prompt = builder.build_prompt(
        task_yaml=task_yaml,
        skills=["yaml-validation"],
    )

    assert "task-1" in prompt
    assert "Validate task YAML" in prompt
    assert "yaml-validation" in prompt.lower()


def test_injects_multiple_skills():
    """Test that multiple skills are injected."""
    builder = PromptBuilder(
        SkillsRegistry(
            Path(__file__).parent.parent / "src" / "chiffon" / "skills"
        )
    )

    task_yaml = "id: task-1\ngoal: Test"

    prompt = builder.build_prompt(
        task_yaml=task_yaml,
        skills=["yaml-validation", "test-driven-development"],
    )

    assert "YAML Validation" in prompt
    assert "Test-Driven Development" in prompt


def test_adds_executor_instructions():
    """Test that executor-specific instructions are included."""
    builder = PromptBuilder(
        SkillsRegistry(
            Path(__file__).parent.parent / "src" / "chiffon" / "skills"
        )
    )

    task_yaml = "id: task-1\ngoal: Test"

    prompt = builder.build_prompt(
        task_yaml=task_yaml,
        skills=[],
    )

    # Should include instructions about what to do
    assert "code" in prompt.lower() or "plan" in prompt.lower()


def test_task_yaml_in_fenced_code_block(builder):
    """Test that task YAML is embedded in a fenced code block."""
    task_yaml = "id: task-99\ngoal: Check fencing"

    prompt = builder.build_prompt(task_yaml=task_yaml, skills=[])

    assert "```yaml" in prompt
    assert "task-99" in prompt
    assert "```" in prompt


def test_system_message_references_plan_section(builder):
    """Test that system message directs LLM to produce a PLAN section."""
    task_yaml = "id: task-1\ngoal: Test"

    prompt = builder.build_prompt(task_yaml=task_yaml, skills=[])

    assert "PLAN" in prompt


def test_system_message_references_code_section(builder):
    """Test that system message directs LLM to produce a CODE section."""
    task_yaml = "id: task-1\ngoal: Test"

    prompt = builder.build_prompt(task_yaml=task_yaml, skills=[])

    assert "CODE" in prompt


def test_system_message_references_verification_section(builder):
    """Test that system message directs LLM to produce a VERIFICATION section."""
    task_yaml = "id: task-1\ngoal: Test"

    prompt = builder.build_prompt(task_yaml=task_yaml, skills=[])

    assert "VERIFICATION" in prompt


def test_empty_skills_list_omits_reference_patterns_header(builder):
    """Test that with no skills the REFERENCE PATTERNS header is omitted."""
    task_yaml = "id: task-1\ngoal: Test"

    prompt = builder.build_prompt(task_yaml=task_yaml, skills=[])

    assert "REFERENCE PATTERNS" not in prompt


def test_skills_produce_reference_patterns_header(builder):
    """Test that injecting skills produces the REFERENCE PATTERNS header."""
    task_yaml = "id: task-1\ngoal: Test"

    prompt = builder.build_prompt(task_yaml=task_yaml, skills=["yaml-validation"])

    assert "REFERENCE PATTERNS" in prompt


def test_unknown_skill_silently_skipped(builder):
    """Test that an unknown/missing skill is skipped without raising."""
    task_yaml = "id: task-1\ngoal: Test"

    prompt = builder.build_prompt(
        task_yaml=task_yaml,
        skills=["nonexistent-skill"],
    )

    # Prompt is still returned; just no content for the missing skill
    assert "task-1" in prompt


def test_default_skills_is_none_or_empty(builder):
    """Test that build_prompt works when skills parameter is omitted."""
    task_yaml = "id: task-1\ngoal: Test"

    prompt = builder.build_prompt(task_yaml=task_yaml)

    assert "task-1" in prompt


def test_max_context_tokens_excludes_skills_over_budget(builder):
    """Skills whose content would exceed max_context_tokens are not injected.

    With max_context_tokens=1, even a single character of skill content would
    push the total over the budget (the system message alone already uses far
    more than 1 token).  Therefore no skill content should appear under the
    REFERENCE PATTERNS header, and the header itself should be absent.
    """
    task_yaml = "id: task-1\ngoal: Test budget enforcement"

    prompt = builder.build_prompt(
        task_yaml=task_yaml,
        skills=["yaml-validation"],
        max_context_tokens=1,
    )

    # Task YAML is always present regardless of budget
    assert "task-1" in prompt
    # No skill content should have been injected
    assert "REFERENCE PATTERNS" not in prompt
