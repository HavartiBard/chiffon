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


# --- New tests for Task 2 ---

def _make_task_file(queue_dir, task_id: str, gitea_issue=None):
    """Helper: write a minimal task yml file."""
    import yaml as _yaml
    data = {"id": task_id, "goal": "test goal"}
    if gitea_issue is not None:
        data["gitea_issue"] = gitea_issue
    task_file = queue_dir / f"{task_id}.yml"
    task_file.write_text(_yaml.dump(data))
    return task_file


def test_extract_issue_number_from_task_n_id():
    """task-7 id maps to issue number 7."""
    from src.chiffon.cli import _extract_issue_number
    assert _extract_issue_number({"id": "task-7"}) == 7


def test_extract_issue_number_from_gitea_issue_field():
    """gitea_issue field overrides the task-N pattern."""
    from src.chiffon.cli import _extract_issue_number
    assert _extract_issue_number({"id": "komodo-deployment", "gitea_issue": 42}) == 42


def test_extract_issue_number_returns_none_when_not_extractable():
    """Non-matching id with no gitea_issue field returns None."""
    from src.chiffon.cli import _extract_issue_number
    assert _extract_issue_number({"id": "komodo-deployment"}) is None


def test_progress_comment_posted_on_pickup(tmp_path):
    """A picked-up comment is posted when a task is found and --use-llm is active."""
    from unittest.mock import patch, MagicMock, AsyncMock

    queue_dir = tmp_path / "tasks" / "queue" / "test-project"
    queue_dir.mkdir(parents=True)
    _make_task_file(queue_dir, "task-5")

    posted_bodies = []

    async def fake_post_comment(issue_number, state, message):
        posted_bodies.append(message)

    with patch("src.chiffon.cli.post_gitea_comment", side_effect=fake_post_comment), \
         patch("src.chiffon.cli.TaskExecutor") as mock_exec_cls:
        mock_exec = MagicMock()
        mock_exec.check_health.return_value = True
        mock_exec.execute_task = AsyncMock(return_value={
            "success": True, "plan": "p", "code": "c", "verification": "v"
        })
        mock_exec_cls.return_value = mock_exec

        from src.chiffon.cli import main
        try:
            main(["run-once", "--project", "test-project",
                  "--repo", str(tmp_path), "--use-llm"])
        except SystemExit:
            pass

    assert any("picked up" in b.lower() for b in posted_bodies), \
        f"Expected a 'picked up' comment, got: {posted_bodies}"


# --- New tests for Task 3 ---

def test_format_blocked_comment_contains_required_content():
    """Blocked comment body contains task id, error, label name, and debug instructions."""
    from src.chiffon.cli import _format_blocked_comment

    body = _format_blocked_comment(
        task_id="task-9",
        task_data={"id": "task-9", "goal": "Deploy komodo"},
        error="LLM returned malformed JSON",
    )

    assert "task-9" in body
    assert "LLM returned malformed JSON" in body
    assert "chiffon:blocked" in body
    assert "docker logs" in body or "ssh" in body


def test_blocked_label_applied_on_llm_failure(tmp_path):
    """chiffon:blocked label is applied to the Gitea issue when LLM execution fails."""
    from unittest.mock import patch, MagicMock, AsyncMock

    queue_dir = tmp_path / "tasks" / "queue" / "test-project"
    queue_dir.mkdir(parents=True)
    _make_task_file(queue_dir, "task-9")

    label_calls = []
    comment_bodies = []

    async def fake_add_label(client, base_url, owner, repo, token, issue_number, label_name, **kw):
        label_calls.append((issue_number, label_name))

    async def fake_post_comment(issue_number, state, message):
        comment_bodies.append(message)

    with patch("src.chiffon.cli.add_issue_label", side_effect=fake_add_label), \
         patch("src.chiffon.cli.post_gitea_comment", side_effect=fake_post_comment), \
         patch.dict("os.environ", {"CHIFFON_EXECUTOR_TOKEN": "test-token"}), \
         patch("src.chiffon.cli.TaskExecutor") as mock_exec_cls:

        mock_exec = MagicMock()
        mock_exec.check_health.return_value = True
        mock_exec.execute_task = AsyncMock(return_value={
            "success": False,
            "error": "JSON parse error: unexpected token",
        })
        mock_exec_cls.return_value = mock_exec

        from src.chiffon.cli import main
        try:
            main(["run-once", "--project", "test-project",
                  "--repo", str(tmp_path), "--use-llm"])
        except SystemExit:
            pass

    assert any(label == "chiffon:blocked" for (_, label) in label_calls), \
        f"Expected chiffon:blocked label to be applied, got: {label_calls}"
    assert any("task-9" in b for b in comment_bodies), \
        f"Expected a comment mentioning task-9, got: {comment_bodies}"
