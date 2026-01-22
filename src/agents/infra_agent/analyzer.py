"""PlaybookAnalyzer service for ansible-lint analysis and improvement suggestions.

Provides:
- Automated ansible-lint execution on failed playbooks
- Categorization of suggestions (idempotency, error_handling, performance, best_practices, standards)
- Template-based reasoning for common rules
- Database persistence for tracking suggestions
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.common.models import PlaybookSuggestion

logger = logging.getLogger(__name__)


class Suggestion(BaseModel):
    """Individual improvement suggestion from ansible-lint.

    Attributes:
        category: Suggestion category (idempotency, error_handling, performance, best_practices, standards)
        rule_id: ansible-lint rule ID (e.g., "no-changed-when", "command-instead-of-module")
        message: Original lint message from ansible-lint
        reasoning: Human-readable explanation of why this matters
        line_number: Line number in playbook where issue found
        file_path: Path to file containing the issue (relative to playbook)
        severity: Severity level (error, warning, info)
    """

    category: str = Field(..., description="Suggestion category")
    rule_id: str = Field(..., description="ansible-lint rule ID")
    message: str = Field(..., description="Lint message")
    reasoning: Optional[str] = Field(None, description="Why this matters")
    line_number: Optional[int] = Field(None, description="Line number")
    file_path: Optional[str] = Field(None, description="File path")
    severity: str = Field(..., description="Severity: error, warning, info")


class AnalysisResult(BaseModel):
    """Result of playbook analysis.

    Attributes:
        playbook_path: Path to analyzed playbook
        total_issues: Total number of issues found
        suggestions: List of categorized suggestions
        by_category: Count of suggestions grouped by category
        analyzed_at: When analysis was performed
    """

    playbook_path: str = Field(..., description="Path to analyzed playbook")
    total_issues: int = Field(..., description="Total number of issues")
    suggestions: list[Suggestion] = Field(
        default_factory=list, description="Categorized suggestions"
    )
    by_category: dict[str, int] = Field(
        default_factory=dict, description="Issue count by category"
    )
    analyzed_at: datetime = Field(
        default_factory=datetime.utcnow, description="Analysis timestamp"
    )


class PlaybookAnalyzer:
    """Service for analyzing playbooks with ansible-lint and generating suggestions.

    Runs ansible-lint on playbook files, categorizes findings by type, generates
    human-readable reasoning, and optionally persists to database.
    """

    # Rule-to-category mapping
    RULE_CATEGORIES = {
        # Idempotency rules
        "no-changed-when": "idempotency",
        "command-instead-of-module": "idempotency",
        "risky-shell-pipe": "idempotency",
        "no-free-form": "idempotency",
        "risky-file-permissions": "idempotency",
        # Error handling rules
        "ignore-errors": "error_handling",
        "no-handler": "error_handling",
        "fqcn": "error_handling",
        "fqcn-builtins": "error_handling",
        "no-relative-paths": "error_handling",
        # Performance rules
        "package-latest": "performance",
        "literal-compare": "performance",
        "no-jinja-when": "performance",
        "deprecated-command-syntax": "performance",
        # Best practices
        "yaml": "best_practices",
        "name": "best_practices",
        "syntax-check": "best_practices",
        "jinja": "best_practices",
        "key-order": "best_practices",
        "no-tabs": "best_practices",
        "args": "best_practices",
        "var-naming": "best_practices",
        "schema": "best_practices",
        # Everything else falls under standards
    }

    # Reasoning templates for common rules
    REASONING_TEMPLATES = {
        "no-changed-when": "Commands should use 'changed_when' to report idempotency status. Without it, the task always reports 'changed' even if nothing was modified, making it harder to track actual changes.",
        "command-instead-of-module": "Using shell/command modules directly bypasses Ansible's idempotency and error handling. Consider using a specialized module instead for better reliability.",
        "risky-shell-pipe": "Shell pipes can hide errors from the first command in the pipeline. Use 'pipefail' or break into separate tasks for better error handling.",
        "ignore-errors": "Using 'ignore_errors: true' silently swallows failures, making debugging difficult. Consider using 'failed_when' for explicit failure conditions instead.",
        "no-handler": "Handlers allow changes to trigger actions only once (like service restarts). Without handlers, you may restart services unnecessarily on every run.",
        "fqcn": "Fully Qualified Collection Names (FQCN) make playbooks more maintainable by explicitly specifying module sources (e.g., 'ansible.builtin.copy' instead of 'copy').",
        "package-latest": "Using 'state: latest' causes packages to update on every run, breaking idempotency. Pin specific versions or use 'state: present' instead.",
        "literal-compare": "Comparing variables directly in 'when' clauses can fail. Use Jinja2 tests like 'is defined' or 'is true' for safer comparisons.",
        "no-jinja-when": "Jinja2 templating in 'when' clauses is redundant and can cause issues. Remove {{ }} and use variables directly.",
        "yaml": "YAML syntax issues can cause playbooks to fail or behave unexpectedly. Fix formatting to ensure reliable parsing.",
        "name": "Tasks without names are harder to debug. Add descriptive names to all tasks for better playbook readability.",
        "syntax-check": "Playbook contains syntax errors that will prevent execution. Review and fix syntax issues.",
        "jinja": "Jinja2 template syntax errors can cause unexpected behavior. Verify template expressions are properly formatted.",
        "args": "Task arguments should be properly structured. Use proper YAML syntax for module arguments.",
        "var-naming": "Variable names should follow Ansible conventions (lowercase with underscores). Consistent naming improves playbook maintainability.",
    }

    def __init__(self, db_session: Optional[Session] = None):
        """Initialize PlaybookAnalyzer.

        Args:
            db_session: Optional SQLAlchemy session for persisting suggestions
        """
        self.db_session = db_session
        self.logger = logging.getLogger(__name__)

    async def analyze_playbook(
        self, playbook_path: str, task_id: Optional[str] = None
    ) -> AnalysisResult:
        """Analyze playbook with ansible-lint and generate categorized suggestions.

        Args:
            playbook_path: Path to playbook file to analyze
            task_id: Optional task UUID for tracking suggestions

        Returns:
            AnalysisResult with categorized suggestions and counts

        Raises:
            FileNotFoundError: If playbook file doesn't exist
            RuntimeError: If ansible-lint is not installed
        """
        self.logger.info(f"Analyzing playbook: {playbook_path}")

        # Verify playbook exists
        if not Path(playbook_path).exists():
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")

        # Run ansible-lint
        try:
            lint_results = self._run_ansible_lint(playbook_path)
        except FileNotFoundError:
            raise RuntimeError(
                "ansible-lint not installed. Install with: pip install ansible-lint"
            )

        # Convert lint results to categorized suggestions
        suggestions = []
        for result in lint_results:
            category = self._categorize_rule(result.get("rule", {}).get("id", ""))
            rule_id = result.get("rule", {}).get("id", "unknown")
            message = result.get("message", "")
            severity = self._map_severity(result.get("level", "warning"))
            line_number = result.get("location", {}).get("lines", {}).get("begin", None)
            file_path = result.get("location", {}).get("path", None)

            reasoning = self._generate_reasoning(rule_id)

            suggestion = Suggestion(
                category=category,
                rule_id=rule_id,
                message=message,
                reasoning=reasoning,
                line_number=line_number,
                file_path=file_path,
                severity=severity,
            )
            suggestions.append(suggestion)

        # Truncate if too many suggestions (keep first 50 of 100+)
        if len(suggestions) > 100:
            self.logger.warning(
                f"Truncating {len(suggestions)} suggestions to 50 (playbook: {playbook_path})"
            )
            suggestions = suggestions[:50]

        # Group by category for summary
        by_category: dict[str, int] = {}
        for suggestion in suggestions:
            by_category[suggestion.category] = (
                by_category.get(suggestion.category, 0) + 1
            )

        analysis_result = AnalysisResult(
            playbook_path=playbook_path,
            total_issues=len(suggestions),
            suggestions=suggestions,
            by_category=by_category,
            analyzed_at=datetime.utcnow(),
        )

        # Persist to database if session provided
        if self.db_session:
            await self._persist_suggestions(analysis_result, task_id)

        self.logger.info(
            f"Analysis complete: {len(suggestions)} suggestions in {len(by_category)} categories"
        )
        return analysis_result

    def _run_ansible_lint(self, playbook_path: str) -> list[dict]:
        """Run ansible-lint on playbook and return JSON results.

        Args:
            playbook_path: Path to playbook file

        Returns:
            List of lint finding dictionaries

        Raises:
            FileNotFoundError: If ansible-lint command not found
            subprocess.TimeoutExpired: If ansible-lint takes >60 seconds
        """
        try:
            result = subprocess.run(
                ["ansible-lint", "--format", "json", "--nocolor", playbook_path],
                capture_output=True,
                text=True,
                timeout=60,
            )

            # ansible-lint returns non-zero when issues found, that's expected
            # Only error if command actually failed (not found, etc.)
            if result.returncode > 2:
                self.logger.error(
                    f"ansible-lint failed with code {result.returncode}: {result.stderr}"
                )
                return []

            # Parse JSON output
            if result.stdout:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse ansible-lint JSON: {e}")
                    return []

            return []

        except FileNotFoundError:
            self.logger.error("ansible-lint command not found")
            raise
        except subprocess.TimeoutExpired:
            self.logger.error(f"ansible-lint timed out after 60s for {playbook_path}")
            return []

    def _categorize_rule(self, rule_id: str) -> str:
        """Map ansible-lint rule ID to suggestion category.

        Args:
            rule_id: ansible-lint rule ID (e.g., "no-changed-when")

        Returns:
            Category string (idempotency, error_handling, performance, best_practices, standards)
        """
        return self.RULE_CATEGORIES.get(rule_id, "standards")

    def _generate_reasoning(self, rule_id: str) -> str:
        """Generate human-readable reasoning for a rule.

        Args:
            rule_id: ansible-lint rule ID

        Returns:
            Reasoning string explaining why this rule matters
        """
        return self.REASONING_TEMPLATES.get(
            rule_id,
            "This rule helps maintain Ansible best practices and playbook quality.",
        )

    def _map_severity(self, level: str) -> str:
        """Map ansible-lint level to severity.

        Args:
            level: ansible-lint level (error, warning, info, etc.)

        Returns:
            Normalized severity (error, warning, info)
        """
        level_lower = level.lower()
        if level_lower in ("error", "fatal"):
            return "error"
        elif level_lower in ("warning", "warn"):
            return "warning"
        else:
            return "info"

    async def _persist_suggestions(
        self, analysis_result: AnalysisResult, task_id: Optional[str] = None
    ) -> None:
        """Persist suggestions to database.

        Args:
            analysis_result: Analysis result with suggestions
            task_id: Optional task UUID for FK relationship
        """
        if not self.db_session:
            return

        # Bulk insert suggestions
        for suggestion in analysis_result.suggestions:
            db_suggestion = PlaybookSuggestion(
                playbook_path=analysis_result.playbook_path,
                task_id=task_id,
                category=suggestion.category,
                rule_id=suggestion.rule_id,
                message=suggestion.message,
                reasoning=suggestion.reasoning,
                line_number=suggestion.line_number,
                severity=suggestion.severity,
                status="pending",
                created_at=analysis_result.analyzed_at,
            )
            self.db_session.add(db_suggestion)

        try:
            self.db_session.commit()
            self.logger.info(
                f"Persisted {len(analysis_result.suggestions)} suggestions for {analysis_result.playbook_path}"
            )
        except Exception as e:
            self.logger.error(f"Failed to persist suggestions: {e}")
            self.db_session.rollback()
            raise
