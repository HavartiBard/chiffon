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

app = typer.Typer()


async def update_gitea_issue(issue_number: int, state: str, message: str) -> None:
    """Update Gitea issue state and add comment."""
    token = os.getenv("CHIFFON_ORCHESTRATOR_TOKEN")
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
) -> None:
    """Run a single task from the queue.

    Finds the first task in tasks/queue/<project>/, executes it, and writes
    the report to tasks/runs/<task-id>/.
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
            issue_number = int(task_id.split("-")[1])

        # Update Gitea issue - mark as in progress
        if issue_number:
            try:
                asyncio.run(update_gitea_issue(
                    issue_number,
                    "open",
                    f"🔄 Chiffon orchestrator taking ownership of this task. Execution started."
                ))
            except Exception as e:
                typer.echo(f"Warning: Could not update Gitea issue: {e}", err=True)

        # Call the engine
        run_engine(str(repo_path), str(queue_dir))

        # Check if task succeeded or failed
        if issue_number:
            report_file = repo_path / "runs" / task_id
            if report_file.exists():
                report_path = sorted(report_file.glob("*/report.json"))
                if report_path:
                    with open(report_path[0]) as f:
                        report = json.load(f)

                    all_passed = all(r.get("exit_code") == 0 for r in report.get("verify_results", []))
                    status = "✓ PASSED" if all_passed else "✗ FAILED"

                    try:
                        asyncio.run(update_gitea_issue(
                            issue_number,
                            "closed" if all_passed else "open",
                            f"{status}\n\nTask execution completed:\n```json\n{json.dumps(report, indent=2)}\n```"
                        ))
                    except Exception as e:
                        typer.echo(f"Warning: Could not update Gitea issue with results: {e}", err=True)

        typer.echo(f"✓ Task completed")

    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


# Entry point for console script
def main(argv: list[str] | None = None) -> Any:
    if argv is None:
        argv = sys.argv[1:]
    return app(argv)
