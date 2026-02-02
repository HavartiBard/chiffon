"""Test-driven development for task materializer."""

import pytest
from pathlib import Path
from src.chiffon.task_materializer import TaskMaterializer


@pytest.mark.asyncio
async def test_materializer_converts_issue_to_task_yaml():
    """Test that TaskMaterializer converts a Gitea issue into task YAML."""
    # Mock Gitea issue data
    issue = {
        "id": 42,
        "number": 10,
        "title": "Implement task YAML loader and validator",
        "body": """## Goal
Create a Python module to parse and validate task YAML files.

## Scope
- `src/chiffon/engine/task_loader.py`

## Constraints
- timeout: 300 seconds
- max_diff_bytes: 50000

## Steps
1. Implement TaskLoader class
2. Create tests

## Verify
- pytest tests/test_task_loader.py passes
- No linting errors""",
    }

    materializer = TaskMaterializer(project="orchestrator-core")
    yaml_str = await materializer.materialize(issue)

    # Verify YAML structure (parse it to validate)
    import yaml
    parsed = yaml.safe_load(yaml_str)

    assert parsed["version"] == "1"
    assert "metadata" in parsed
    assert "goal" in parsed
    assert "steps" in parsed
    assert "verify" in parsed
    assert "constraints" in parsed

    # Verify content
    assert "task_loader" in parsed["scope"]["allowed_write_globs"][0]
    assert parsed["constraints"]["timeout_seconds"] == 300
    assert parsed["constraints"]["max_diff_bytes"] == 50000


@pytest.mark.asyncio
async def test_materializer_handles_missing_sections():
    """Test that materializer gracefully handles missing markdown sections."""
    issue = {
        "id": 43,
        "number": 11,
        "title": "Simple issue",
        "body": "No sections here, just plain text.",
    }

    materializer = TaskMaterializer(project="orchestrator-core")
    yaml_str = await materializer.materialize(issue)

    import yaml
    parsed = yaml.safe_load(yaml_str)

    # Should have defaults and not crash
    assert parsed["version"] == "1"
    assert parsed["goal"] == ""  # Empty goal is ok
    assert parsed["constraints"]["timeout_seconds"] == 300  # Default
    assert len(parsed["verify"]) == 0  # Empty verify is ok


@pytest.mark.asyncio
async def test_materializer_extracts_metadata():
    """Test that metadata is correctly populated from issue."""
    issue = {
        "id": 44,
        "number": 8,
        "title": "Test issue",
        "body": "## Goal\nTest the metadata extraction",
    }

    materializer = TaskMaterializer(project="guardrails")
    yaml_str = await materializer.materialize(issue)

    import yaml
    parsed = yaml.safe_load(yaml_str)

    assert parsed["metadata"]["id"] == "task-8"
    assert parsed["metadata"]["source"] == "gitea:guardrails:8"
    assert parsed["metadata"]["created_by"] == "claude"
    assert "created_at" in parsed["metadata"]


@pytest.mark.asyncio
async def test_materializer_parses_constraints():
    """Test that constraints section is correctly parsed."""
    issue = {
        "id": 45,
        "number": 9,
        "title": "Complex task",
        "body": """## Goal
Test constraint parsing

## Constraints
- timeout: 600 seconds
- max_diff_bytes: 100000""",
    }

    materializer = TaskMaterializer(project="orchestrator-core")
    yaml_str = await materializer.materialize(issue)

    import yaml
    parsed = yaml.safe_load(yaml_str)

    # Should parse timeout and max_diff from constraint section
    assert parsed["constraints"]["timeout_seconds"] == 600
    assert parsed["constraints"]["max_diff_bytes"] == 100000
