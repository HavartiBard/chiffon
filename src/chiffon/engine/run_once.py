"""
Engine for running a single task from the queue.

This module implements minimal MRL0 run-once behavior as described in the
requirements. It is intentionally lightweight and does not depend on the
full original project codebase.

The public entry point is :func:`run`, which accepts a repository path and a
queue directory path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_git(args: List[str], cwd: Path) -> str:
    """Run a git command and return its stdout.

    Raises :class:`RuntimeError` if the command exits non-zero.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()

# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run(repo_path: str | Path, queue_dir: str | Path) -> None:
    repo = Path(repo_path).resolve()
    queue = Path(queue_dir).resolve()

    # 1. Find next task file (lexicographically first *.yml or *.yaml)
    candidates = sorted(
        list(queue.glob("*.yml")) + list(queue.glob("*.yaml")),
        key=lambda p: p.name,
    )
    if not candidates:
        raise FileNotFoundError("No task file found in queue directory")

    task_file = candidates[0]

    # 2. Parse YAML schema
    with task_file.open("rt", encoding="utf-8") as f:
        data: Dict[str, Any] = yaml.safe_load(f)

    task_id: str = data["id"]
    goal: str = data.get("goal", "")
    edits: List[Dict[str, Any]] = data.get("edits", [])
    verify_cmds: List[str] = [v["cmd"] for v in data.get("verify", [])]

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    branch_name = f"chiffon/{task_id}/{timestamp}"

    # 3. Create branch
    _run_git(["checkout", "-b", branch_name], cwd=repo)

    # 4. Apply edits safely
    for edit in edits:
        op: str = edit["op"]
        rel_path: Path = Path(edit["file"])  # repo-relative
        target = (repo / rel_path).resolve()
        if not str(target).startswith(str(repo)):
            raise RuntimeError(f"Path escape detected: {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        text = edit.get("text", "")

        if op == "write":
            target.write_text(text, encoding="utf-8")
        elif op == "append":
            with target.open("a", encoding="utf-8") as f:
                f.write(text)
        else:
            raise ValueError(f"Unsupported edit operation: {op}")

    # 5. Commit changes
    _run_git(["add", "."], cwd=repo)
    commit_msg = f"chiffon: {task_id} - {goal}".strip()
    _run_git(["commit", "-m", commit_msg], cwd=repo)

    # 6. Run verify commands
    results: List[Dict[str, Any]] = []
    for cmd in verify_cmds:
        try:
            completed = subprocess.run(
                cmd,
                shell=True,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=300,
            )
            results.append(
                {
                    "cmd": cmd,
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
        except subprocess.TimeoutExpired as exc:
            results.append({"cmd": cmd, "exit_code": -1, "stdout": exc.stdout or "", "stderr": exc.stderr or str(exc)})

    # 7. Write report.json
    run_dir = repo / "runs" / task_id / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.json"
    report_data: Dict[str, Any] = {
        "task_id": task_id,
        "goal": goal,
        "branch": branch_name,
        "commit_hash": _run_git(["rev-parse", "HEAD"], cwd=repo),
        "timestamp": timestamp,
        "verify_results": results,
    }
    report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    # 8. Move task file to done or failed
    dest_dir = queue / ("done" if all(r["exit_code"] == 0 for r in results) else "failed")
    dest_dir.mkdir(exist_ok=True)
    shutil.move(str(task_file), str(dest_dir / task_file.name))

    # End of run

