"""Tests for the enhanced Task schema with LLM execution fields.

These tests cover the new fields added to the Task dataclass for LLM-driven
execution: applicable_skills, source, parent_issue, subtask, description,
suggested_approach, scope, and constraints. They also exercise the
Task.from_dict() classmethod factory.
"""

import pytest
from src.chiffon.queue.file_queue import Task


# ---------------------------------------------------------------------------
# applicable_skills field
# ---------------------------------------------------------------------------

def test_task_has_applicable_skills():
    """Task includes applicable_skills field populated by from_dict."""
    task_data = {
        "id": "task-1",
        "goal": "Test",
        "edits": [],
        "verify": [],
        "applicable_skills": ["yaml-validation", "test-driven-development"],
    }

    task = Task.from_dict(task_data)
    assert task.applicable_skills == ["yaml-validation", "test-driven-development"]


def test_applicable_skills_defaults_to_empty_list():
    """applicable_skills defaults to [] when not provided."""
    task_data = {
        "id": "task-2",
        "goal": "No skills",
    }

    task = Task.from_dict(task_data)
    assert task.applicable_skills == []


# ---------------------------------------------------------------------------
# Metadata fields: source, parent_issue, subtask
# ---------------------------------------------------------------------------

def test_task_has_metadata():
    """Task includes metadata fields for decomposed subtask tracking."""
    task_data = {
        "id": "task-7-a",
        "parent_issue": 7,
        "subtask": "1/4",
        "goal": "Test",
        "edits": [],
        "verify": [],
    }

    task = Task.from_dict(task_data)
    assert task.parent_issue == 7
    assert task.subtask == "1/4"


def test_task_source_field():
    """Task includes a source field for tracing back to Gitea issues."""
    task_data = {
        "id": "task-7-b",
        "goal": "Test source",
        "source": "gitea:chiffon:7",
    }

    task = Task.from_dict(task_data)
    assert task.source == "gitea:chiffon:7"


def test_metadata_fields_default_to_none_or_empty():
    """parent_issue and subtask default to None, source defaults to ''."""
    task = Task.from_dict({"id": "task-3", "goal": "Minimal"})
    assert task.parent_issue is None
    assert task.subtask is None
    assert task.source == ""


# ---------------------------------------------------------------------------
# LLM hint fields: description, suggested_approach
# ---------------------------------------------------------------------------

def test_task_has_description_and_suggested_approach():
    """Task includes description and suggested_approach fields."""
    task_data = {
        "id": "task-4",
        "goal": "Implement feature X",
        "description": "Add X to the Y module so that Z works correctly.",
        "suggested_approach": "Start with the data model, then the API layer.",
    }

    task = Task.from_dict(task_data)
    assert task.description == "Add X to the Y module so that Z works correctly."
    assert task.suggested_approach == "Start with the data model, then the API layer."


def test_description_and_suggested_approach_default_to_empty_string():
    """description and suggested_approach default to '' when absent."""
    task = Task.from_dict({"id": "task-5", "goal": "Bare minimum"})
    assert task.description == ""
    assert task.suggested_approach == ""


# ---------------------------------------------------------------------------
# scope and constraints fields
# ---------------------------------------------------------------------------

def test_task_has_scope_constraints():
    """Task includes scope and constraints dicts."""
    task_data = {
        "id": "task-1",
        "goal": "Test",
        "edits": [],
        "verify": [],
        "scope": {
            "allowed_write_globs": ["src/**"],
            "allowed_read_globs": ["src/**", "tests/**"],
        },
        "constraints": {
            "max_files_changed": 5,
            "max_diff_bytes": 10000,
            "timeout_seconds": 300,
            "denylisted_commands": ["rm -rf"],
        },
    }

    task = Task.from_dict(task_data)
    assert task.scope["allowed_write_globs"] == ["src/**"]
    assert task.scope["allowed_read_globs"] == ["src/**", "tests/**"]
    assert task.constraints["timeout_seconds"] == 300
    assert task.constraints["max_files_changed"] == 5
    assert task.constraints["denylisted_commands"] == ["rm -rf"]


def test_scope_defaults_to_empty_dict():
    """scope defaults to {} when not provided."""
    task = Task.from_dict({"id": "task-6", "goal": "No scope"})
    assert task.scope == {}


def test_constraints_defaults_to_empty_dict():
    """constraints defaults to {} when not provided."""
    task = Task.from_dict({"id": "task-7", "goal": "No constraints"})
    assert task.constraints == {}


# ---------------------------------------------------------------------------
# from_dict classmethod: key mapping and backward compatibility
# ---------------------------------------------------------------------------

def test_from_dict_maps_verify_key_to_verifies():
    """from_dict maps the YAML 'verify' key to the Task.verifies field."""
    task_data = {
        "id": "task-8",
        "goal": "Verify key mapping",
        "verify": [{"cmd": "pytest"}],
    }

    task = Task.from_dict(task_data)
    assert len(task.verifies) == 1
    assert task.verifies[0].cmd == "pytest"


def test_from_dict_maps_edits():
    """from_dict correctly parses the edits list."""
    task_data = {
        "id": "task-9",
        "goal": "Edit mapping",
        "edits": [{"op": "write", "file": "foo.py", "text": "# content"}],
    }

    task = Task.from_dict(task_data)
    assert len(task.edits) == 1
    assert task.edits[0].op == "write"
    assert task.edits[0].file == "foo.py"


def test_from_dict_full_task():
    """from_dict handles a fully-specified task with all new fields."""
    task_data = {
        "id": "task-full",
        "goal": "Full task",
        "source": "gitea:chiffon:42",
        "parent_issue": 42,
        "subtask": "2/5",
        "description": "Detailed description for the LLM.",
        "suggested_approach": "Use TDD.",
        "applicable_skills": ["yaml-validation"],
        "scope": {"allowed_write_globs": ["src/**"]},
        "constraints": {"timeout_seconds": 120},
        "edits": [{"op": "append", "file": "README.md", "text": "new line"}],
        "verify": [{"cmd": "echo done"}],
    }

    task = Task.from_dict(task_data)

    assert task.id == "task-full"
    assert task.goal == "Full task"
    assert task.source == "gitea:chiffon:42"
    assert task.parent_issue == 42
    assert task.subtask == "2/5"
    assert task.description == "Detailed description for the LLM."
    assert task.suggested_approach == "Use TDD."
    assert task.applicable_skills == ["yaml-validation"]
    assert task.scope == {"allowed_write_globs": ["src/**"]}
    assert task.constraints == {"timeout_seconds": 120}
    assert len(task.edits) == 1
    assert len(task.verifies) == 1


def test_from_dict_requires_id_and_goal():
    """from_dict raises ValueError if id or goal is missing."""
    with pytest.raises((ValueError, KeyError)):
        Task.from_dict({"goal": "No id"})

    with pytest.raises((ValueError, KeyError)):
        Task.from_dict({"id": "task-x"})


def test_task_direct_instantiation_still_works():
    """Existing Task(id=..., goal=...) constructor still works unchanged."""
    task = Task(id="legacy-task", goal="Legacy goal")
    assert task.id == "legacy-task"
    assert task.goal == "Legacy goal"
    assert task.edits == []
    assert task.verifies == []
    # New fields have defaults
    assert task.applicable_skills == []
    assert task.source == ""
    assert task.parent_issue is None
    assert task.subtask is None
    assert task.description == ""
    assert task.suggested_approach == ""
    assert task.scope == {}
    assert task.constraints == {}
