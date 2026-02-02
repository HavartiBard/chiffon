"""Convert Gitea issues to executable task YAML files."""

import re
from typing import Any
from datetime import datetime, timezone
from uuid import uuid4
import yaml


class TaskMaterializer:
    """Converts Gitea issues into task YAML format."""

    def __init__(self, project: str):
        """Initialize materializer.

        Args:
            project: Project name (orchestrator-core, guardrails, etc.)
        """
        self.project = project

    def _parse_markdown_sections(self, body: str) -> dict[str, str]:
        """Extract markdown sections from issue body.

        Looks for ## Section patterns and returns dict of section_name -> content.

        Example:
            "## Goal\\nThis is the goal" → {"goal": "This is the goal"}
        """
        sections = {}
        pattern = r'^## (\w+)\s*\n(.*?)(?=^##|\Z)'
        matches = re.finditer(pattern, body, re.MULTILINE | re.DOTALL)

        for match in matches:
            section_name = match.group(1).lower()
            content = match.group(2).strip()
            sections[section_name] = content

        return sections

    async def materialize(self, issue: dict[str, Any]) -> str:
        """Convert Gitea issue to task YAML string.

        Args:
            issue: Gitea issue object

        Returns:
            Task YAML as string (format expected by engine)
        """
        sections = self._parse_markdown_sections(issue["body"])

        # Build minimal task YAML structure that engine expects
        task = {
            "id": f"task-{issue['number']}",
            "goal": sections.get("goal", ""),
            "edits": [],  # Tasks typically define steps in markdown, not YAML edits
            "verify": [],
        }

        # Parse verify section - convert to list of {cmd: ...} dicts
        if "verify" in sections:
            verify_commands = [line.strip() for line in sections["verify"].split("\n") if line.strip()]
            task["verify"] = [{"cmd": cmd} for cmd in verify_commands]

        return yaml.dump(task, default_flow_style=False, sort_keys=False)
