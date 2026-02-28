"""Command line interface for chiffon."""

import sys
import json
import asyncio
import os
from typing import Any
from pathlib import Path

import typer
import yaml
import httpx

from src.chiffon.engine.run_once import run as run_engine
from src.chiffon.gitea_client import GiteaClient
from chiffon.executor.executor import TaskExecutor
from chiffon.queue.file_queue import Task

app = typer.Typer()


async def update_gitea_issue(issue_number: int, state: str, message: str) -> None:
    """Update Gitea issue state and add comment."""
    # Use executor token, fall back to orchestrator or GITEA_TOKEN
    token = (os.getenv("CHIFFON_EXECUTOR_TOKEN") or os.getenv("CHIFFON_EXECUTOR01_TOKEN")
             or os.getenv("GITEA_TOKEN") or os.getenv("CHIFFON_ORCHESTRATOR_TOKEN"))
    if not token:
        return

    async with httpx.AsyncClient() as client:
        base_url = "https://code.klsll.com"
        repo_owner = "HavartiBard"
        repo_name = "chiffon"

        # Update issue state
        await client.patch(
            f"{base_url}/api/v1/repos/{repo_owner}/{repo_name}/issues/{issue_number}",
            json={"state": state},
            headers={"Authorization": f"token {token}"}
        )

        # Add comment
        await client.post(
            f"{base_url}/api/v1/repos/{repo_owner}/{repo_name}/issues/{issue_number}/comments",
            json={"body": message},
            headers={"Authorization": f"token {token}"}
        )


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


async def post_gitea_comment(issue_number: int | None, state: str, message: str) -> None:
    """Post a comment to a Gitea issue and optionally update its state.

    No-ops silently if no token is configured or issue_number is None.
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


def _fire(coro) -> None:
    """Run an async Gitea notification coroutine, swallowing all exceptions.

    Note: Uses asyncio.run() which requires no running event loop. Safe for
    the current synchronous CLI context. If chiffon is ever embedded in an
    async scheduler, this will need to use loop.run_until_complete() instead.
    """
    try:
        asyncio.run(coro)
    except Exception as e:
        typer.echo(f"Warning: Gitea notification failed: {e}", err=True)


def _format_blocked_comment(task_id: str, task_data: dict, error: str) -> str:
    """Format the structured blocked comment body for a stuck task."""
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
        f"ssh root@192.168.20.14 "
        f"cat /mnt/user/appdata/chiffon-executor/repo/tasks/queue/*/{task_id}.yml\n"
        "```\n\n"
        "**To retry:** fix the task YAML, commit to main, then remove the `chiffon:blocked` "
        "label from this issue. Chiffon will re-attempt on the next cron cycle."
    )


def _handle_blocked(
    issue_number: int | None,
    task_id: str,
    task_data: dict,
    error: str,
) -> None:
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
                issue_number, "chiffon:blocked", color="#e11d48",
            )

    _fire(_apply_label())


@app.command(name="run-once")
def run_once(
    project: str = typer.Option(..., help="Project name (e.g., orchestrator-core)"),
    repo: str = typer.Option(".", help="Repository path"),
    use_llm: bool = typer.Option(
        False,
        "--use-llm",
        help="Use LLM inference via TaskExecutor instead of the plain engine.",
    ),
    llm_url: str = typer.Option(
        None,
        "--llm-url",
        help="URL for the llama.cpp server (default: LLAMA_SERVER_URL env or http://localhost:8000).",
    ),
) -> None:
    """Run a single task from the queue.

    Finds the first task in tasks/queue/<project>/, executes it, and writes
    the report to tasks/runs/<task-id>/.

    When --use-llm is passed, the task is forwarded to TaskExecutor which
    calls a local llama.cpp server to generate a plan, code, and verification
    strategy.  When omitted the existing rule-based engine is used unchanged.
    """
    try:
        repo_path = Path(repo).resolve()
        queue_dir = repo_path / "tasks" / "queue" / project

        if not queue_dir.exists():
            typer.echo(f"Error: Queue directory not found: {queue_dir}")
            raise SystemExit(1)

        # Find next task
        candidates = sorted(
            list(queue_dir.glob("*.yml")) + list(queue_dir.glob("*.yaml")),
            key=lambda p: p.name,
        )
        if not candidates:
            typer.echo("No tasks in queue")
            return

        task_file = candidates[0]

        # Parse task to extract issue number
        with task_file.open("r") as f:
            task_data = yaml.safe_load(f)

        task_id = task_data.get("id", "")
        issue_number = _extract_issue_number(task_data)

        if use_llm:
            # Milestone 1: picked up
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

            # Milestone 2: inference started
            _fire(post_gitea_comment(
                issue_number, "open",
                f"🤖 LLM health OK — inference started for `{task_id}`…",
            ))

            task = Task.from_dict(task_data)
            try:
                result = asyncio.run(executor.execute_task(task))
            except Exception as exc:
                result = {"success": False, "error": str(exc)}

            if result["success"]:
                typer.echo("Task completed via LLM")
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
                # Milestone 3: success
                _fire(post_gitea_comment(issue_number, "closed", summary))
            else:
                _handle_blocked(issue_number, task_id, task_data, result.get("error", "unknown"))
                raise SystemExit(1)

        else:
            # --- Plain engine path (original behaviour) ---
            run_engine(str(repo_path), str(queue_dir))

            # Check if task succeeded or failed by inspecting the report
            if issue_number is not None:
                report_file = repo_path / "runs" / task_id
                if report_file.exists():
                    report_path = sorted(report_file.glob("*/report.json"))
                    if report_path:
                        with open(report_path[0]) as f:
                            report = json.load(f)

                        all_passed = all(
                            r.get("exit_code") == 0 for r in report.get("verify_results", [])
                        )
                        status = "PASSED" if all_passed else "FAILED"

                        try:
                            asyncio.run(update_gitea_issue(
                                issue_number,
                                "closed" if all_passed else "open",
                                f"{status}\n\nTask execution completed:\n```json\n{json.dumps(report, indent=2)}\n```",
                            ))
                        except Exception as e:
                            typer.echo(
                                f"Warning: Could not update Gitea issue with results: {e}", err=True
                            )

        typer.echo("Task completed")

    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


# Entry point for console script
def main(argv: list[str] | None = None) -> Any:
    """Parse CLI arguments and dispatch to run_once.

    Accepts both ``chiffon run-once --project foo`` and ``chiffon --project foo``
    forms (the leading "run-once" subcommand is optional for backward
    compatibility).  Uses argparse directly to avoid a typer 0.9 / click 8
    incompatibility where ``flag_value=None`` causes all options to be treated
    as boolean flags.
    """
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    # Strip optional leading subcommand name so callers can pass either form.
    if argv and argv[0] == "run-once":
        argv = argv[1:]

    parser = argparse.ArgumentParser(prog="chiffon run-once")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument(
        "--use-llm",
        action="store_true",
        default=False,
        help="Use LLM inference via TaskExecutor",
    )
    parser.add_argument("--llm-url", default=None, help="llama.cpp server URL")

    # Print help and exit 0 when --help is requested (matches typer behaviour).
    if "--help" in argv or "-h" in argv:
        parser.print_help()
        raise SystemExit(0)

    # Unknown argv (e.g. bare "chiffon run-once" with no args) exits with code 2.
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        parser.print_usage(sys.stderr)
        sys.stderr.write(f"error: unrecognized arguments: {' '.join(unknown)}\n")
        raise SystemExit(2)

    run_once(
        project=args.project,
        repo=args.repo,
        use_llm=args.use_llm,
        llm_url=args.llm_url,
    )
