# Chiffon Feedback Loops Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add two lightweight feedback mechanisms to the chiffon executor: granular Gitea progress comments throughout LLM execution, and a `chiffon:blocked` label + structured comment when execution fails — plus an Obsidian skill document for Raclette to oversee blocked tasks.

**Architecture:** All changes are in `src/chiffon/cli.py`. Two new async helper functions manage Gitea label lifecycle (get-or-create, then attach to issue). The `run_once` command gains four comment milestones in the LLM path and writes a structured "I'm stuck" comment on failure. The Raclette instructions are a skill note written to the shared Obsidian vault on Unraid.

**Tech Stack:** Python 3.12, httpx (async HTTP), pytest + unittest.mock for tests, Ansible raw for Obsidian write.

---

## Context: how the code works today

`src/chiffon/cli.py` has one command `run-once`. In `--use-llm` mode:

1. Finds the first `*.yml` in `tasks/queue/<project>/`
2. Extracts issue number from task id if it matches `task-N` (e.g. `task-7` → issue #7)
3. Posts one "taking ownership" comment to Gitea
4. Calls `TaskExecutor.check_health()` then `execute_task()`
5. Posts one pass/fail comment and exits

**Gaps being fixed:**
- Only two Gitea touchpoints (start + end) — no visibility during LLM inference
- Failure comment has no structure — just "LLM execution failed: \<error\>"
- No label applied — no way for Raclette to filter blocked tasks
- Task ids that aren't `task-N` (e.g. `komodo-deployment`) never get any Gitea updates

Run tests with: `poetry run pytest tests/test_cli_run_once.py -v`

---

## Task 1: Gitea label helpers

**Files:**
- Modify: `src/chiffon/cli.py` (add two new async functions before `run_once`)
- Create: `tests/test_gitea_label_helpers.py`

### Step 1: Write failing tests

```python
# tests/test_gitea_label_helpers.py
"""Tests for Gitea label helper functions in cli."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.chiffon.cli import get_or_create_label, add_issue_label


@pytest.mark.asyncio
async def test_get_or_create_label_returns_existing_id():
    """Returns the label ID when label already exists."""
    mock_client = AsyncMock()
    mock_list_resp = MagicMock()
    mock_list_resp.status_code = 200
    mock_list_resp.json.return_value = [
        {"id": 42, "name": "chiffon:blocked", "color": "#e11d48"},
        {"id": 7,  "name": "bug",             "color": "#d73a4a"},
    ]
    mock_client.get.return_value = mock_list_resp

    label_id = await get_or_create_label(
        mock_client, "https://code.klsll.com", "HavartiBard", "chiffon",
        "test-token", "chiffon:blocked"
    )

    assert label_id == 42
    mock_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_label_creates_when_missing():
    """Creates the label and returns new ID when label does not exist."""
    mock_client = AsyncMock()

    mock_list_resp = MagicMock()
    mock_list_resp.status_code = 200
    mock_list_resp.json.return_value = []
    mock_client.get.return_value = mock_list_resp

    mock_create_resp = MagicMock()
    mock_create_resp.status_code = 201
    mock_create_resp.json.return_value = {"id": 99, "name": "chiffon:blocked"}
    mock_client.post.return_value = mock_create_resp

    label_id = await get_or_create_label(
        mock_client, "https://code.klsll.com", "HavartiBard", "chiffon",
        "test-token", "chiffon:blocked", color="#e11d48"
    )

    assert label_id == 99
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[1]["json"]["name"] == "chiffon:blocked"
    assert call_kwargs[1]["json"]["color"] == "#e11d48"


@pytest.mark.asyncio
async def test_add_issue_label_calls_gitea_api():
    """add_issue_label looks up or creates label then POSTs to issue labels endpoint."""
    mock_client = AsyncMock()

    # Label list returns existing label
    mock_list_resp = MagicMock()
    mock_list_resp.status_code = 200
    mock_list_resp.json.return_value = [{"id": 5, "name": "chiffon:blocked"}]
    mock_client.get.return_value = mock_list_resp

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_client.post.return_value = mock_post_resp

    await add_issue_label(
        mock_client, "https://code.klsll.com", "HavartiBard", "chiffon",
        "test-token", issue_number=12, label_name="chiffon:blocked"
    )

    # Should POST to issue labels endpoint with label id 5
    label_post_call = mock_client.post.call_args
    assert "/issues/12/labels" in label_post_call[0][0]
    assert label_post_call[1]["json"]["labels"] == [5]
```

### Step 2: Run to confirm they fail

```bash
poetry run pytest tests/test_gitea_label_helpers.py -v
```

Expected: `ImportError: cannot import name 'get_or_create_label' from 'src.chiffon.cli'`

### Step 3: Add the two helper functions to cli.py

Add these two functions **between** `update_gitea_issue` and the `@app.command` decorator (after line 46 in the current file):

```python
async def get_or_create_label(
    client: httpx.AsyncClient,
    base_url: str,
    repo_owner: str,
    repo_name: str,
    token: str,
    label_name: str,
    color: str = "#e11d48",
) -> int | None:
    """Return ID of label_name in repo, creating it if absent."""
    headers = {"Authorization": f"token {token}"}
    resp = await client.get(
        f"{base_url}/api/v1/repos/{repo_owner}/{repo_name}/labels",
        headers=headers,
    )
    if resp.status_code == 200:
        for label in resp.json():
            if label["name"] == label_name:
                return label["id"]
    # Not found — create it
    resp = await client.post(
        f"{base_url}/api/v1/repos/{repo_owner}/{repo_name}/labels",
        json={"name": label_name, "color": color},
        headers=headers,
    )
    if resp.status_code in (200, 201):
        return resp.json()["id"]
    return None


async def add_issue_label(
    client: httpx.AsyncClient,
    base_url: str,
    repo_owner: str,
    repo_name: str,
    token: str,
    issue_number: int,
    label_name: str,
    color: str = "#e11d48",
) -> None:
    """Attach label_name to an issue, creating the label in the repo if needed."""
    label_id = await get_or_create_label(
        client, base_url, repo_owner, repo_name, token, label_name, color
    )
    if label_id is None:
        return
    await client.post(
        f"{base_url}/api/v1/repos/{repo_owner}/{repo_name}/issues/{issue_number}/labels",
        json={"labels": [label_id]},
        headers={"Authorization": f"token {token}"},
    )
```

### Step 4: Run tests to confirm they pass

```bash
poetry run pytest tests/test_gitea_label_helpers.py -v
```

Expected: 3 passed

### Step 5: Commit

```bash
git add src/chiffon/cli.py tests/test_gitea_label_helpers.py
git commit -m "feat(cli): add get_or_create_label and add_issue_label helpers"
```

---

## Task 2: Gitea progress comments + flexible issue_number extraction

**Files:**
- Modify: `src/chiffon/cli.py` (`run_once` function body)
- Modify: `tests/test_cli_run_once.py` (extend with new cases)

### Background

The current issue_number extraction only works for `task-N` ids. Tasks like `komodo-deployment` never get any Gitea updates. The task YAML already supports a `gitea_issue` field (in the schema) — use it as a fallback.

New comment milestones in `--use-llm` path:
1. **Pickup** — "Task `{task_id}` picked up…" (replaces current generic "taking ownership" message)
2. **Inference started** — "LLM inference started…" (new, before `execute_task`)
3. **Success** — structured output with each file as a fenced code block (replaces current flat dump)
4. **Failure** — see Task 3

### Step 1: Write failing tests

Add these to `tests/test_cli_run_once.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import yaml


def _make_task_file(queue_dir: Path, task_id: str, gitea_issue: int | None = None) -> Path:
    data = {"id": task_id, "goal": "test goal"}
    if gitea_issue is not None:
        data["gitea_issue"] = gitea_issue
    task_file = queue_dir / f"{task_id}.yml"
    task_file.write_text(yaml.dump(data))
    return task_file


def test_issue_number_extracted_from_task_n_id(tmp_path):
    """task-7 → issue_number 7 (existing behaviour)."""
    from src.chiffon.cli import _extract_issue_number
    assert _extract_issue_number({"id": "task-7"}) == 7


def test_issue_number_extracted_from_gitea_issue_field(tmp_path):
    """gitea_issue: 42 overrides the task-N pattern."""
    from src.chiffon.cli import _extract_issue_number
    assert _extract_issue_number({"id": "komodo-deployment", "gitea_issue": 42}) == 42


def test_issue_number_none_when_not_extractable():
    """Non-matching id with no gitea_issue → None."""
    from src.chiffon.cli import _extract_issue_number
    assert _extract_issue_number({"id": "komodo-deployment"}) is None


@pytest.mark.asyncio
async def test_progress_comment_posted_on_pickup(tmp_path):
    """A 'picked up' Gitea comment is posted as soon as a task is found."""
    queue_dir = tmp_path / "tasks" / "queue" / "test-project"
    queue_dir.mkdir(parents=True)
    _make_task_file(queue_dir, "task-5", gitea_issue=None)
    # task-5 → issue 5

    posted_bodies = []

    async def fake_post_comment(issue_number, state, message):
        posted_bodies.append(message)

    with patch("src.chiffon.cli.post_gitea_comment", side_effect=fake_post_comment):
        with patch("src.chiffon.cli.TaskExecutor") as mock_exec_cls:
            mock_exec = MagicMock()
            mock_exec.check_health.return_value = True
            mock_exec.execute_task = AsyncMock(return_value={"success": True, "plan": "", "code": "", "verification": ""})
            mock_exec_cls.return_value = mock_exec

            from src.chiffon.cli import main
            try:
                main(["run-once", "--project", "test-project", "--repo", str(tmp_path), "--use-llm"])
            except SystemExit:
                pass

    assert any("picked up" in b.lower() for b in posted_bodies), \
        f"Expected 'picked up' comment, got: {posted_bodies}"
```

### Step 2: Run to confirm they fail

```bash
poetry run pytest tests/test_cli_run_once.py -v -k "issue_number or progress"
```

Expected: `ImportError: cannot import name '_extract_issue_number'` and `cannot import name 'post_gitea_comment'`

### Step 3: Refactor cli.py — extract helpers and add progress comments

**3a. Extract `_extract_issue_number` as a standalone function** (just above `run_once`):

```python
def _extract_issue_number(task_data: dict) -> int | None:
    """Return Gitea issue number from task data, or None.

    Checks ``gitea_issue`` field first, then falls back to parsing ``task-N`` ids.
    """
    if "gitea_issue" in task_data:
        try:
            return int(task_data["gitea_issue"])
        except (TypeError, ValueError):
            pass
    task_id = task_data.get("id", "")
    if task_id.startswith("task-"):
        try:
            return int(task_id.split("-")[1])
        except (IndexError, ValueError):
            pass
    return None
```

**3b. Extract `post_gitea_comment` as a standalone async function** that replaces the inline `update_gitea_issue` calls (keeps the same logic, just named clearly):

```python
async def post_gitea_comment(issue_number: int, state: str, message: str) -> None:
    """Post a comment to a Gitea issue and optionally update its state.

    No-ops silently if CHIFFON_EXECUTOR_TOKEN / GITEA_TOKEN is not set
    or if issue_number is None.
    """
    token = (
        os.getenv("CHIFFON_EXECUTOR_TOKEN")
        or os.getenv("CHIFFON_EXECUTOR01_TOKEN")
        or os.getenv("GITEA_TOKEN")
        or os.getenv("CHIFFON_ORCHESTRATOR_TOKEN")
    )
    if not token or issue_number is None:
        return
    base_url = "https://code.klsll.com"
    repo_owner = "HavartiBard"
    repo_name = "chiffon"
    async with httpx.AsyncClient() as client:
        if state:
            await client.patch(
                f"{base_url}/api/v1/repos/{repo_owner}/{repo_name}/issues/{issue_number}",
                json={"state": state},
                headers={"Authorization": f"token {token}"},
            )
        await client.post(
            f"{base_url}/api/v1/repos/{repo_owner}/{repo_name}/issues/{issue_number}/comments",
            json={"body": message},
            headers={"Authorization": f"token {token}"},
        )
```

**3c. Rewrite the `--use-llm` block in `run_once`** to use these helpers and add milestones:

Replace the entire `if use_llm:` block with:

```python
        if use_llm:
            # --- Milestone 1: picked up ---
            _fire(post_gitea_comment(
                issue_number, "open",
                f"⚙️ Task `{task_id}` picked up — running LLM health check…",
            ))

            executor = TaskExecutor(
                repo_path=repo_path,
                queue_path=queue_dir,
                llm_server_url=llm_url or None,
            )
            try:
                executor.check_health()
            except RuntimeError as e:
                typer.echo(f"Error: {e}", err=True)
                _fire(post_gitea_comment(
                    issue_number, "open",
                    f"❌ LLM health check failed for `{task_id}`:\n\n```\n{e}\n```",
                ))
                raise SystemExit(1)

            # --- Milestone 2: inference started ---
            _fire(post_gitea_comment(
                issue_number, "open",
                f"🤖 LLM health OK — inference started for `{task_id}`…",
            ))

            task = Task.from_dict(task_data)
            result = asyncio.run(executor.execute_task(task))

            if result["success"]:
                typer.echo("Task completed via LLM")
                # --- Milestone 3: structured success output ---
                plan = result.get("plan", "").strip()
                code = result.get("code", "").strip()
                verification = result.get("verification", "").strip()
                sections = []
                if plan:
                    sections.append(f"## Plan\n{plan}")
                if code:
                    sections.append(f"## Generated files\n```\n{code}\n```")
                if verification:
                    sections.append(f"## Verification\n{verification}")
                summary = (
                    f"✅ LLM execution complete for `{task_id}`.\n\n"
                    + "\n\n".join(sections)
                )
                _fire(post_gitea_comment(issue_number, "closed", summary))
            else:
                # Milestone 4 is in Task 3 — blocked state
                _handle_blocked(issue_number, task_id, task_data, result.get("error", "unknown"))
                raise SystemExit(1)
```

**3d. Add the `_fire` convenience wrapper** (removes repetitive try/except at every callsite):

```python
def _fire(coro) -> None:
    """Run an async Gitea notification coroutine, swallowing exceptions."""
    try:
        asyncio.run(coro)
    except Exception as e:
        typer.echo(f"Warning: Gitea notification failed: {e}", err=True)
```

Note: `_handle_blocked` is added in Task 3.

### Step 4: Run tests

```bash
poetry run pytest tests/test_cli_run_once.py -v
```

Expected: all passing

### Step 5: Commit

```bash
git add src/chiffon/cli.py tests/test_cli_run_once.py
git commit -m "feat(cli): add progress milestones and flexible issue number extraction"
```

---

## Task 3: chiffon:blocked label + structured failure comment

**Files:**
- Modify: `src/chiffon/cli.py` (add `_handle_blocked`)
- Modify: `tests/test_cli_run_once.py` (add blocked state tests)

### Step 1: Write failing tests

Add to `tests/test_cli_run_once.py`:

```python
@pytest.mark.asyncio
async def test_blocked_label_applied_on_llm_failure(tmp_path):
    """chiffon:blocked label is applied to the issue when LLM execution fails."""
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
         patch("src.chiffon.cli.TaskExecutor") as mock_exec_cls:

        mock_exec = MagicMock()
        mock_exec.check_health.return_value = True
        mock_exec.execute_task = AsyncMock(return_value={
            "success": False,
            "error": "JSON parse error: unexpected token"
        })
        mock_exec_cls.return_value = mock_exec

        from src.chiffon.cli import main
        try:
            main(["run-once", "--project", "test-project", "--repo", str(tmp_path), "--use-llm"])
        except SystemExit:
            pass

    assert any(label == "chiffon:blocked" for (_, label) in label_calls), \
        f"Expected chiffon:blocked label, got: {label_calls}"


def test_blocked_comment_contains_error_and_instructions(tmp_path):
    """Blocked comment body contains error text and Raclette help instructions."""
    from src.chiffon.cli import _format_blocked_comment

    body = _format_blocked_comment(
        task_id="task-9",
        task_data={"id": "task-9", "goal": "Deploy komodo"},
        error="LLM returned malformed JSON",
    )

    assert "task-9" in body
    assert "LLM returned malformed JSON" in body
    assert "chiffon:blocked" in body          # label name mentioned so Raclette knows what to clear
    assert "docker logs" in body.lower() or "ssh" in body.lower()  # contains debug instructions
```

### Step 2: Run to confirm they fail

```bash
poetry run pytest tests/test_cli_run_once.py -v -k "blocked"
```

Expected: `ImportError: cannot import name '_handle_blocked'` and `'_format_blocked_comment'`

### Step 3: Add `_format_blocked_comment` and `_handle_blocked` to cli.py

Add just before `run_once`:

```python
def _format_blocked_comment(task_id: str, task_data: dict, error: str) -> str:
    """Format the structured 'I am stuck' comment body for a blocked task."""
    goal = task_data.get("goal", "(no goal)")
    source = task_data.get("source", "")
    source_line = f"\n**Source:** `{source}`" if source else ""
    return (
        f"🚧 **Chiffon is blocked on `{task_id}`**{source_line}\n\n"
        f"**Goal:** {goal}\n\n"
        f"**Error:**\n```\n{error}\n```\n\n"
        "---\n"
        "**Raclette — to investigate:**\n\n"
        "```bash\n"
        "# Tail executor logs\n"
        "ssh root@192.168.20.14 docker logs chiffon-executor --tail 50\n\n"
        "# Read the task file\n"
        f"ssh root@192.168.20.14 cat /mnt/user/appdata/chiffon-executor/repo/tasks/queue/*/{task_id}.yml\n"
        "```\n\n"
        "**To retry:** fix the task YAML, commit to main, then remove the `chiffon:blocked` "
        "label from this issue. Chiffon will re-attempt on the next cron cycle."
    )


def _handle_blocked(issue_number: int | None, task_id: str, task_data: dict, error: str) -> None:
    """Post a structured blocked comment and apply the chiffon:blocked label."""
    typer.echo(f"Error: LLM execution failed: {error}", err=True)

    token = (
        os.getenv("CHIFFON_EXECUTOR_TOKEN")
        or os.getenv("CHIFFON_EXECUTOR01_TOKEN")
        or os.getenv("GITEA_TOKEN")
        or os.getenv("CHIFFON_ORCHESTRATOR_TOKEN")
    )
    if not token or issue_number is None:
        return

    body = _format_blocked_comment(task_id, task_data, error)
    _fire(post_gitea_comment(issue_number, "open", body))

    base_url = "https://code.klsll.com"
    repo_owner = "HavartiBard"
    repo_name = "chiffon"

    async def _apply_label() -> None:
        async with httpx.AsyncClient() as client:
            await add_issue_label(
                client, base_url, repo_owner, repo_name, token,
                issue_number, "chiffon:blocked", color="#e11d48"
            )

    _fire(_apply_label())
```

### Step 4: Run all tests

```bash
poetry run pytest tests/test_cli_run_once.py tests/test_gitea_label_helpers.py -v
```

Expected: all passing

### Step 5: Commit

```bash
git add src/chiffon/cli.py tests/test_cli_run_once.py
git commit -m "feat(cli): add chiffon:blocked label and structured failure comment"
```

---

## Task 4: Wire up komodo-deployment task to a Gitea issue

**Files:**
- Modify: `tasks/queue/homelab-infra/komodo-deployment.yml`

The `komodo-deployment` task has no `gitea_issue` field, so none of the new feedback goes anywhere. Fix this by creating a Gitea issue and linking it.

### Step 1: Create the Gitea issue

```bash
curl -s -X POST "https://code.klsll.com/api/v1/repos/HavartiBard/chiffon/issues" \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "chiffon task: komodo-deployment",
    "body": "Track execution of `tasks/queue/homelab-infra/komodo-deployment.yml`.\n\nSee Obsidian: `projects/homelab-infra/komodo-deployment.md`"
  }' | jq '.number'
```

Note the returned issue number.

### Step 2: Add gitea_issue to the task YAML

Edit `tasks/queue/homelab-infra/komodo-deployment.yml` — add after the `source:` line:

```yaml
gitea_issue: <number from step 1>
```

### Step 3: Commit and push

```bash
git add tasks/queue/homelab-infra/komodo-deployment.yml
git commit -m "feat(queue): link komodo-deployment task to Gitea issue"
git push
```

---

## Task 5: Write Raclette skill note to Obsidian

**Files:**
- Create on Unraid: `/mnt/user/appdata/obsidian/vaults/homelab/shared/skills/oversee-chiffon.md`

The note is a skill Raclette can load to understand how to supervise chiffon workers. Write it to a temp file locally, then scp to Unraid.

### Step 1: Write the note

Create `/tmp/oversee-chiffon.md` with this content:

```markdown
---
type: skill
skill-for: raclette
category: agent-supervision
tags:
  - chiffon
  - supervision
  - gitea
  - ssh
last-updated: '2026-02-27'
---

# Skill: Oversee Chiffon Workers

Use this skill when you need to monitor chiffon task progress, diagnose failures,
or intervene on blocked tasks.

## How chiffon works

Chiffon is a cron-based LLM executor that runs every 30 minutes inside Docker on Unraid.

```
chiffon-executor container (Unraid 192.168.20.14)
  ↓ polls
tasks/queue/<project>/<task>.yml  (in the chiffon Gitea repo)
  ↓ calls LLM (LM Studio on spraycheese)
  ↓ posts progress to Gitea issue
  ↓ moves task to done/ or failed/
```

## Finding blocked tasks

Blocked tasks have the `chiffon:blocked` label on the chiffon repo:

```bash
# Via MCP (preferred)
mcporter call director.gitea_list_issues repo=HavartiBard/chiffon labels=chiffon:blocked state=open

# Via curl
curl -s "https://code.klsll.com/api/v1/repos/HavartiBard/chiffon/issues?labels=chiffon:blocked&state=open" \
  -H "Authorization: token $GITEA_TOKEN" | jq '.[] | {number, title, updated_at}'
```

## Reading task details

Each Gitea issue for a chiffon task has:
- The original task goal in the title
- Progress comments from chiffon (picked up → inference started → result)
- A structured blocked comment with the exact error when stuck

Read the issue comments to understand where it failed.

## Inspecting executor logs

SSH into Unraid to read real-time logs:

```bash
ssh root@192.168.20.14 docker logs chiffon-executor --tail 100
ssh root@192.168.20.14 docker logs chiffon-executor --since 30m
```

To follow logs while a task runs:

```bash
ssh root@192.168.20.14 docker logs -f chiffon-executor
```

## Reading and editing the task file

Task files live in the chiffon Gitea repo at:
`tasks/queue/<project>/<task-id>.yml`

The repo on Unraid is at:
`/mnt/user/appdata/chiffon-executor/repo/tasks/queue/`

```bash
# Read current task
ssh root@192.168.20.14 cat /mnt/user/appdata/chiffon-executor/repo/tasks/queue/homelab-infra/komodo-deployment.yml
```

To fix and retry, edit the task via Gitea (MCP commit) or clone locally, then:

## Retrying a blocked task

1. **Read the error** from the Gitea issue comment
2. **Fix the root cause** — usually the task description, suggested_approach, or a skill reference
3. **Commit the fix** to `main` in the chiffon repo via Gitea MCP or git
4. **Remove the `chiffon:blocked` label** from the issue — chiffon will re-attempt on next cron cycle
5. **Watch the logs** to confirm pickup

```bash
# Remove the blocked label (replace ISSUE_NUMBER and LABEL_ID)
curl -s -X DELETE \
  "https://code.klsll.com/api/v1/repos/HavartiBard/chiffon/issues/ISSUE_NUMBER/labels/LABEL_ID" \
  -H "Authorization: token $GITEA_TOKEN"
```

To get the label ID:

```bash
curl -s "https://code.klsll.com/api/v1/repos/HavartiBard/chiffon/labels" \
  -H "Authorization: token $GITEA_TOKEN" | jq '.[] | select(.name=="chiffon:blocked") | .id'
```

## Manually triggering a run

The executor runs on cron (every 30 min). To trigger immediately:

```bash
ssh root@192.168.20.14 docker exec chiffon-executor \
  chiffon run-once --project homelab-infra --use-llm
```

## What Raclette can provide as assistance

If chiffon is stuck on generating a specific piece of code, you can:

1. **Post a clarifying comment** on the blocked Gitea issue — the next run will include comments in the issue context if chiffon is extended to read them
2. **Edit the task YAML** directly via Gitea MCP to improve `suggested_approach` or `description`
3. **Generate the code yourself** and commit it to homelab-infra as a PR, then close the chiffon issue

## Chiffon repo reference

- **Gitea:** https://code.klsll.com/HavartiBard/chiffon
- **Issues:** https://code.klsll.com/HavartiBard/chiffon/issues?labels=chiffon:blocked
- **Executor container:** `chiffon-executor` on Unraid
- **Queue path:** `/mnt/user/appdata/chiffon-executor/repo/tasks/queue/`
- **Cron:** every 30 min
```

### Step 2: Copy to Unraid

```bash
scp -i ~/.ssh/id_ed25519_homelab /tmp/oversee-chiffon.md \
  root@192.168.20.14:/mnt/user/appdata/obsidian/vaults/homelab/shared/skills/oversee-chiffon.md
```

### Step 3: Verify

```bash
ansible unraid-server -m raw \
  -a "ls -la /mnt/user/appdata/obsidian/vaults/homelab/shared/skills/" \
  -i ~/projects/homelab-infra/ansible/inventory/hosts.yml
```

Expected: `oversee-chiffon.md` appears in the listing.

---

## Task 6: Push and smoke-test

### Step 1: Run full test suite

```bash
poetry run pytest tests/test_cli_run_once.py tests/test_gitea_label_helpers.py -v
```

Expected: all passing

### Step 2: Push to Gitea

```bash
git push
```

### Step 3: Verify executor picks up the updated code

The executor container pulls the repo on each cron cycle. To force an immediate re-pull:

```bash
ansible unraid-server -m raw \
  -a "docker exec chiffon-executor git -C /work pull --ff-only" \
  -i ~/projects/homelab-infra/ansible/inventory/hosts.yml
```

Then manually trigger a harmless dry-run (project with empty queue — no tasks, just checks):

```bash
ansible unraid-server -m raw \
  -a "docker exec chiffon-executor chiffon run-once --project homelab-infra" \
  -i ~/projects/homelab-infra/ansible/inventory/hosts.yml
```

Expected output: `No tasks in queue` (since all tasks are in `done/` or need `gitea_issue` to be set first)

---

## Summary of changes

| File | Change |
|---|---|
| `src/chiffon/cli.py` | +`get_or_create_label`, +`add_issue_label`, +`_extract_issue_number`, +`_format_blocked_comment`, +`_handle_blocked`, +`_fire`, +`post_gitea_comment`, refactored `run_once` |
| `tests/test_gitea_label_helpers.py` | New — 3 tests for label helpers |
| `tests/test_cli_run_once.py` | +4 tests for progress milestones and blocked state |
| `tasks/queue/homelab-infra/komodo-deployment.yml` | +`gitea_issue: <N>` |
| Obsidian `shared/skills/oversee-chiffon.md` | New — Raclette supervision skill |
