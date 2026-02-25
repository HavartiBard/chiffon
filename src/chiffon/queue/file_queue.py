"""
File‑Queue task parsing utilities.

This module implements a very small subset of the *Task* format that the
Orchestrator uses when it consumes work from the ``tasks/`` directory.

The public API consists of three data classes – :class:`Task`,
:class:`TaskEdit` and :class:`TaskVerify` – plus a helper function
``load_task()`` which loads a task file, validates the payload against the
schema defined by the data classes and returns an instance that can be used by
the rest of the system.

The tests in ``tests/test_file_queue.py`` exercise the following behaviour:

* A valid task file is parsed correctly.
* Missing required fields raise a :class:`ValueError`.
* Invalid ``op`` values also raise an error.

The implementation uses only standard library modules and the lightweight
``yaml`` package that is already part of the repository’s dependencies.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import yaml


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class TaskEdit:
    """Represents a single edit operation for a file.

    Attributes
    ----------
    op: str
        Either ``"append"`` or ``"write"``.  The value is validated by
        :func:`load_task`.
    file: str
        Path to the target file relative to the repository root.
    text: str
        Text that should be appended or used as the new file contents.
    """

    op: str
    file: str
    text: str

    def __post_init__(self) -> None:
        if self.op not in {"append", "write"}:
            raise ValueError(f"Invalid edit operation '{self.op}'. Expected 'append' or 'write'.")


@dataclass(slots=True)
class TaskVerify:
    """Represents a verification command.

    The orchestrator only cares about the command string; any additional
    context that might be needed in the future can be added here without
    breaking the existing API.
    """

    cmd: str


@dataclass
class Task:
    """Top‑level task representation.

    Parameters
    ----------
    id: str
        Unique identifier for the task.
    goal: str
        Human readable description of what the task should achieve.
    edits: List[TaskEdit]
        Optional list of file edit operations.
    verifies: List[TaskVerify]
        Optional list of verification commands.

    LLM execution fields (all optional with safe defaults)
    -------------------------------------------------------
    applicable_skills: List[str]
        Skill names to inject into the LLM prompt (e.g. ``["yaml-validation"]``).
    source: str
        Trace origin, e.g. ``"gitea:chiffon:7"``.
    parent_issue: Optional[int]
        Parent issue number for subtask tracking.
    subtask: Optional[str]
        Subtask index string, e.g. ``"1/4"``.
    description: str
        Thin description forwarded to the LLM for context.
    suggested_approach: str
        Hint from the orchestrator to guide the LLM's reasoning.
    scope: Dict[str, Any]
        Filesystem access constraints, e.g. ``allowed_write_globs``.
    constraints: Dict[str, Any]
        Execution constraints, e.g. ``timeout_seconds``, ``max_files_changed``.
    """

    # Core fields (pre-existing)
    id: str
    goal: str
    edits: List[TaskEdit] = field(default_factory=list)
    verifies: List[TaskVerify] = field(default_factory=list)

    # New LLM execution fields
    applicable_skills: List[str] = field(default_factory=list)
    source: str = ""
    parent_issue: Optional[int] = None
    subtask: Optional[str] = None
    description: str = ""
    suggested_approach: str = ""
    scope: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create a :class:`Task` from a raw dictionary (e.g. parsed YAML).

        Handles the ``verify`` → ``verifies`` key rename and delegates
        edit/verify list parsing to the module-level helpers so that
        :class:`TaskEdit` and :class:`TaskVerify` objects are constructed
        correctly.

        Parameters
        ----------
        data:
            Dictionary with at minimum ``"id"`` and ``"goal"`` keys.

        Returns
        -------
        Task
            Fully constructed task instance.

        Raises
        ------
        KeyError
            If ``"id"`` or ``"goal"`` are absent.
        ValueError
            If an edit entry has an invalid ``op`` value or is malformed.
        """
        id_ = data["id"]
        goal = data["goal"]

        edits = _parse_edits(data.get("edits"))
        verifies = _parse_verify(data.get("verify"))

        return cls(
            id=id_,
            goal=goal,
            edits=edits,
            verifies=verifies,
            applicable_skills=list(data.get("applicable_skills") or []),
            source=data.get("source", ""),
            parent_issue=data.get("parent_issue"),
            subtask=data.get("subtask"),
            description=data.get("description", ""),
            suggested_approach=data.get("suggested_approach", ""),
            scope=dict(data.get("scope") or {}),
            constraints=dict(data.get("constraints") or {}),
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def _parse_edits(edits_data: Iterable | None) -> List[TaskEdit]:
    if not edits_data:
        return []
    if not isinstance(edits_data, (list, tuple)):
        raise ValueError("'edits' must be a list of edit dictionaries")
    edits: List[TaskEdit] = []
    for idx, item in enumerate(edits_data):
        try:
            op = item["op"]
            file_ = item["file"]
            text = item["text"]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Edit entry {idx} missing required key: {exc.args[0]}") from None
        edits.append(TaskEdit(op=op, file=file_, text=text))
    return edits


def _parse_verify(verify_data: Iterable | None) -> List[TaskVerify]:
    if not verify_data:
        return []
    if not isinstance(verify_data, (list, tuple)):
        raise ValueError("'verify' must be a list of command dictionaries")
    verifies: List[TaskVerify] = []
    for idx, item in enumerate(verify_data):
        try:
            cmd = item["cmd"]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Verify entry {idx} missing required key: {exc.args[0]}") from None
        verifies.append(TaskVerify(cmd=cmd))
    return verifies


def load_task(task_path: pathlib.Path) -> Task:
    """Load a task YAML file and return a :class:`Task` instance.

    Parameters
    ----------
    task_path
        Path to the YAML file that represents a task.

    Returns
    -------
    Task
        The parsed and validated task object.

    Raises
    ------
    FileNotFoundError
        If ``task_path`` does not exist.
    ValueError
        If required fields are missing or contain invalid values.
    """

    if not task_path.is_file():
        raise FileNotFoundError(f"Task file '{task_path}' does not exist")

    data = yaml.safe_load(task_path.read_text(encoding="utf-8")) or {}

    # Basic required fields
    try:
        id_ = data["id"]
        goal = data["goal"]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Task missing required key: {exc.args[0]}") from None

    edits_data = data.get("edits")
    verify_data = data.get("verify")

    edits = _parse_edits(edits_data)
    verifies = _parse_verify(verify_data)

    return Task(id=id_, goal=goal, edits=edits, verifies=verifies)
