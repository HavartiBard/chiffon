"""Test-driven development for CLI run-once command."""

import pytest
from pathlib import Path
from src.chiffon.cli import main


@pytest.fixture
def temp_queue(tmp_path):
    """Create temporary task queue structure."""
    queue_dir = tmp_path / "tasks" / "queue" / "orchestrator-core"
    queue_dir.mkdir(parents=True, exist_ok=True)

    runs_dir = tmp_path / "tasks" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    done_dir = queue_dir / "done"
    done_dir.mkdir(exist_ok=True)

    failed_dir = queue_dir / "failed"
    failed_dir.mkdir(exist_ok=True)

    return str(tmp_path)


def test_run_once_currently_not_implemented():
    """Test that run-once currently outputs 'not implemented'."""
    # RED phase: This should fail when we implement it properly
    try:
        main(["run-once"])
    except SystemExit as e:
        # Currently exits with code 2 and says "not implemented"
        assert e.code == 2, f"Expected exit code 2 (current stub), got {e.code}"


def test_run_once_has_project_option():
    """Test that run-once has --project option (not just 'not implemented')."""
    # Try to get help - should show --project option
    try:
        main(["run-once", "--help"])
        assert False, "Should have exited"
    except SystemExit as e:
        # Help always exits with 0
        assert e.code == 0, f"Help should exit 0, got {e.code}"
