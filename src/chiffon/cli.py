"""Command line interface for chiffon."""

import sys
from typing import Any
from pathlib import Path

import typer

from src.chiffon.engine.run_once import run as run_engine

app = typer.Typer()


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

        # Call the engine
        run_engine(str(repo_path), str(queue_dir))
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
