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
    token = os.getenv("CHIFFON_EXECUTOR01_TOKEN") or os.getenv("GITEA_TOKEN") or os.getenv("CHIFFON_ORCHESTRATOR_TOKEN")
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
        issue_number = None
        if task_id.startswith("task-"):
            try:
                issue_number = int(task_id.split("-")[1])
            except (IndexError, ValueError):
                issue_number = None

        # Update Gitea issue - mark as in progress
        if issue_number:
            try:
                asyncio.run(update_gitea_issue(
                    issue_number,
                    "open",
                    "Chiffon orchestrator taking ownership of this task. Execution started."
                ))
            except Exception as e:
                typer.echo(f"Warning: Could not update Gitea issue: {e}", err=True)

        if use_llm:
            # --- LLM execution path ---
            executor = TaskExecutor(
                repo_path=repo_path,
                queue_path=queue_dir,
                llm_server_url=llm_url or None,
            )

            # Health check before attempting execution
            try:
                executor.check_health()
            except RuntimeError as e:
                typer.echo(f"Error: {e}", err=True)
                raise SystemExit(1)

            task = Task.from_dict(task_data)
            result = asyncio.run(executor.execute_task(task))

            if result["success"]:
                typer.echo("Task completed via LLM")
                typer.echo(f"Plan:\n{result['plan']}")
                if issue_number:
                    try:
                        summary = (
                            "LLM execution completed.\n\n"
                            f"**Plan:**\n{result['plan']}\n\n"
                            f"**Code:**\n```python\n{result['code']}\n```\n\n"
                            f"**Verification:**\n{result['verification']}"
                        )
                        asyncio.run(update_gitea_issue(issue_number, "closed", summary))
                    except Exception as e:
                        typer.echo(f"Warning: Could not update Gitea issue: {e}", err=True)
            else:
                typer.echo(f"Error: LLM execution failed: {result.get('error', 'unknown')}", err=True)
                if issue_number:
                    try:
                        asyncio.run(update_gitea_issue(
                            issue_number,
                            "open",
                            f"LLM execution failed: {result.get('error', 'unknown')}",
                        ))
                    except Exception as e:
                        typer.echo(f"Warning: Could not update Gitea issue: {e}", err=True)
                raise SystemExit(1)

        else:
            # --- Plain engine path (original behaviour) ---
            run_engine(str(repo_path), str(queue_dir))

            # Check if task succeeded or failed by inspecting the report
            if issue_number:
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
    if argv is None:
        argv = sys.argv[1:]
    return app(argv)
