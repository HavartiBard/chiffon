"""Tests for PlaybookAnalyzer service.

Test coverage:
- Suggestion model validation
- AnalysisResult model validation and grouping
- Rule categorization (5 categories)
- Reasoning generation for common rules
- ansible-lint subprocess execution (mocked)
- Database persistence
- InfraAgent integration
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.agents.infra_agent.analyzer import (
    AnalysisResult,
    PlaybookAnalyzer,
    Suggestion,
)


class TestSuggestionModel:
    """Test Suggestion Pydantic model validation."""

    def test_suggestion_valid(self):
        """Test valid suggestion creation."""
        suggestion = Suggestion(
            category="idempotency",
            rule_id="no-changed-when",
            message="Commands should not change things if nothing needs doing",
            reasoning="This improves idempotency",
            line_number=42,
            file_path="tasks/main.yml",
            severity="warning",
        )

        assert suggestion.category == "idempotency"
        assert suggestion.rule_id == "no-changed-when"
        assert suggestion.severity == "warning"
        assert suggestion.line_number == 42

    def test_suggestion_optional_fields(self):
        """Test suggestion with optional fields as None."""
        suggestion = Suggestion(
            category="standards",
            rule_id="unknown-rule",
            message="Some generic message",
            reasoning=None,
            line_number=None,
            file_path=None,
            severity="info",
        )

        assert suggestion.reasoning is None
        assert suggestion.line_number is None
        assert suggestion.file_path is None


class TestAnalysisResultModel:
    """Test AnalysisResult Pydantic model validation."""

    def test_analysis_result_valid(self):
        """Test valid analysis result creation."""
        suggestions = [
            Suggestion(
                category="idempotency",
                rule_id="no-changed-when",
                message="Test message",
                severity="warning",
            ),
            Suggestion(
                category="error_handling",
                rule_id="ignore-errors",
                message="Test message 2",
                severity="error",
            ),
        ]

        result = AnalysisResult(
            playbook_path="/path/to/playbook.yml",
            total_issues=2,
            suggestions=suggestions,
            by_category={"idempotency": 1, "error_handling": 1},
        )

        assert result.total_issues == 2
        assert len(result.suggestions) == 2
        assert result.by_category["idempotency"] == 1
        assert result.by_category["error_handling"] == 1

    def test_analysis_result_empty(self):
        """Test analysis result with no issues."""
        result = AnalysisResult(
            playbook_path="/path/to/clean.yml",
            total_issues=0,
            suggestions=[],
            by_category={},
        )

        assert result.total_issues == 0
        assert len(result.suggestions) == 0
        assert result.by_category == {}


class TestRuleCategorization:
    """Test rule-to-category mapping."""

    def test_idempotency_rules(self):
        """Test idempotency category rules."""
        analyzer = PlaybookAnalyzer()

        assert analyzer._categorize_rule("no-changed-when") == "idempotency"
        assert analyzer._categorize_rule("command-instead-of-module") == "idempotency"
        assert analyzer._categorize_rule("risky-shell-pipe") == "idempotency"
        assert analyzer._categorize_rule("no-free-form") == "idempotency"
        assert analyzer._categorize_rule("risky-file-permissions") == "idempotency"

    def test_error_handling_rules(self):
        """Test error_handling category rules."""
        analyzer = PlaybookAnalyzer()

        assert analyzer._categorize_rule("ignore-errors") == "error_handling"
        assert analyzer._categorize_rule("no-handler") == "error_handling"
        assert analyzer._categorize_rule("fqcn") == "error_handling"
        assert analyzer._categorize_rule("fqcn-builtins") == "error_handling"
        assert analyzer._categorize_rule("no-relative-paths") == "error_handling"

    def test_performance_rules(self):
        """Test performance category rules."""
        analyzer = PlaybookAnalyzer()

        assert analyzer._categorize_rule("package-latest") == "performance"
        assert analyzer._categorize_rule("literal-compare") == "performance"
        assert analyzer._categorize_rule("no-jinja-when") == "performance"
        assert analyzer._categorize_rule("deprecated-command-syntax") == "performance"

    def test_best_practices_rules(self):
        """Test best_practices category rules."""
        analyzer = PlaybookAnalyzer()

        assert analyzer._categorize_rule("yaml") == "best_practices"
        assert analyzer._categorize_rule("name") == "best_practices"
        assert analyzer._categorize_rule("syntax-check") == "best_practices"
        assert analyzer._categorize_rule("jinja") == "best_practices"
        assert analyzer._categorize_rule("key-order") == "best_practices"
        assert analyzer._categorize_rule("no-tabs") == "best_practices"
        assert analyzer._categorize_rule("args") == "best_practices"
        assert analyzer._categorize_rule("var-naming") == "best_practices"
        assert analyzer._categorize_rule("schema") == "best_practices"

    def test_standards_default(self):
        """Test standards category as default."""
        analyzer = PlaybookAnalyzer()

        assert analyzer._categorize_rule("unknown-rule") == "standards"
        assert analyzer._categorize_rule("some-other-rule") == "standards"


class TestReasoningGeneration:
    """Test reasoning template generation."""

    def test_common_rules_have_reasoning(self):
        """Test that common rules have specific reasoning templates."""
        analyzer = PlaybookAnalyzer()

        # Test a few key rules
        assert "idempotency" in analyzer._generate_reasoning("no-changed-when")
        assert "module" in analyzer._generate_reasoning("command-instead-of-module")
        assert "errors" in analyzer._generate_reasoning("ignore-errors")
        assert "FQCN" in analyzer._generate_reasoning("fqcn")
        assert "latest" in analyzer._generate_reasoning("package-latest")
        assert "YAML" in analyzer._generate_reasoning("yaml")

    def test_unknown_rule_default_reasoning(self):
        """Test default reasoning for unknown rules."""
        analyzer = PlaybookAnalyzer()

        reasoning = analyzer._generate_reasoning("unknown-rule-id")
        assert "best practices" in reasoning
        assert "quality" in reasoning


class TestSeverityMapping:
    """Test severity normalization."""

    def test_error_severity(self):
        """Test error severity mapping."""
        analyzer = PlaybookAnalyzer()

        assert analyzer._map_severity("error") == "error"
        assert analyzer._map_severity("ERROR") == "error"
        assert analyzer._map_severity("fatal") == "error"
        assert analyzer._map_severity("FATAL") == "error"

    def test_warning_severity(self):
        """Test warning severity mapping."""
        analyzer = PlaybookAnalyzer()

        assert analyzer._map_severity("warning") == "warning"
        assert analyzer._map_severity("WARNING") == "warning"
        assert analyzer._map_severity("warn") == "warning"
        assert analyzer._map_severity("WARN") == "warning"

    def test_info_severity(self):
        """Test info severity mapping."""
        analyzer = PlaybookAnalyzer()

        assert analyzer._map_severity("info") == "info"
        assert analyzer._map_severity("INFO") == "info"
        assert analyzer._map_severity("notice") == "info"
        assert analyzer._map_severity("debug") == "info"


class TestAnsibleLintExecution:
    """Test ansible-lint subprocess execution (mocked)."""

    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    def test_ansible_lint_success(self, mock_run):
        """Test successful ansible-lint execution."""
        mock_run.return_value = MagicMock(
            returncode=2,  # ansible-lint returns 2 when issues found
            stdout=json.dumps(
                [
                    {
                        "rule": {"id": "no-changed-when"},
                        "message": "Commands should have changed_when",
                        "level": "warning",
                        "location": {"path": "tasks/main.yml", "lines": {"begin": 10}},
                    }
                ]
            ),
            stderr="",
        )

        analyzer = PlaybookAnalyzer()
        result = analyzer._run_ansible_lint("/path/to/playbook.yml")

        assert len(result) == 1
        assert result[0]["rule"]["id"] == "no-changed-when"
        mock_run.assert_called_once()

    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    def test_ansible_lint_no_issues(self, mock_run):
        """Test ansible-lint with no issues found."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="[]",
            stderr="",
        )

        analyzer = PlaybookAnalyzer()
        result = analyzer._run_ansible_lint("/path/to/clean.yml")

        assert result == []

    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    def test_ansible_lint_parse_error(self, mock_run):
        """Test ansible-lint with JSON parse error."""
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout="invalid json {",
            stderr="",
        )

        analyzer = PlaybookAnalyzer()
        result = analyzer._run_ansible_lint("/path/to/playbook.yml")

        assert result == []

    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    def test_ansible_lint_not_found(self, mock_run):
        """Test ansible-lint command not found."""
        mock_run.side_effect = FileNotFoundError("ansible-lint not found")

        analyzer = PlaybookAnalyzer()

        with pytest.raises(FileNotFoundError):
            analyzer._run_ansible_lint("/path/to/playbook.yml")

    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    def test_ansible_lint_timeout(self, mock_run):
        """Test ansible-lint timeout."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("ansible-lint", 60)

        analyzer = PlaybookAnalyzer()
        result = analyzer._run_ansible_lint("/path/to/playbook.yml")

        assert result == []


class TestPlaybookAnalyzerIntegration:
    """Test PlaybookAnalyzer full workflow."""

    @pytest.mark.asyncio
    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    async def test_analyze_playbook_full_workflow(self, mock_run, tmp_path):
        """Test full analysis workflow from playbook to result."""
        # Create temporary playbook
        playbook_path = tmp_path / "test.yml"
        playbook_path.write_text(
            """
---
- name: Test playbook
  hosts: all
  tasks:
    - name: Run command
      command: echo hello
"""
        )

        # Mock ansible-lint output
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout=json.dumps(
                [
                    {
                        "rule": {"id": "no-changed-when"},
                        "message": "Commands should have changed_when",
                        "level": "warning",
                        "location": {"path": str(playbook_path), "lines": {"begin": 6}},
                    },
                    {
                        "rule": {"id": "command-instead-of-module"},
                        "message": "Use shell module instead",
                        "level": "warning",
                        "location": {"path": str(playbook_path), "lines": {"begin": 6}},
                    },
                ]
            ),
            stderr="",
        )

        analyzer = PlaybookAnalyzer()
        result = await analyzer.analyze_playbook(str(playbook_path))

        assert result.total_issues == 2
        assert result.playbook_path == str(playbook_path)
        assert "idempotency" in result.by_category
        assert result.by_category["idempotency"] == 2
        assert len(result.suggestions) == 2

    @pytest.mark.asyncio
    async def test_analyze_playbook_not_found(self):
        """Test analysis with non-existent playbook."""
        analyzer = PlaybookAnalyzer()

        with pytest.raises(FileNotFoundError):
            await analyzer.analyze_playbook("/nonexistent/playbook.yml")

    @pytest.mark.asyncio
    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    async def test_analyze_playbook_ansible_lint_not_installed(self, mock_run):
        """Test analysis when ansible-lint not installed."""
        mock_run.side_effect = FileNotFoundError("ansible-lint not found")

        # Create temporary playbook
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("---\n- hosts: all\n  tasks: []\n")
            playbook_path = f.name

        analyzer = PlaybookAnalyzer()

        with pytest.raises(RuntimeError, match="ansible-lint not installed"):
            await analyzer.analyze_playbook(playbook_path)

        # Cleanup
        Path(playbook_path).unlink()

    @pytest.mark.asyncio
    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    async def test_analyze_playbook_truncation(self, mock_run, tmp_path):
        """Test that large results are truncated to 50 suggestions."""
        # Create temporary playbook
        playbook_path = tmp_path / "large.yml"
        playbook_path.write_text("---\n- hosts: all\n  tasks: []\n")

        # Mock 150 lint findings
        findings = [
            {
                "rule": {"id": f"rule-{i}"},
                "message": f"Message {i}",
                "level": "warning",
                "location": {"path": str(playbook_path), "lines": {"begin": i}},
            }
            for i in range(150)
        ]

        mock_run.return_value = MagicMock(
            returncode=2,
            stdout=json.dumps(findings),
            stderr="",
        )

        analyzer = PlaybookAnalyzer()
        result = await analyzer.analyze_playbook(str(playbook_path))

        # Should be truncated to 50
        assert result.total_issues == 50
        assert len(result.suggestions) == 50


class TestDatabasePersistence:
    """Test database persistence of suggestions."""

    @pytest.mark.asyncio
    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    async def test_persist_suggestions(self, mock_run, tmp_path):
        """Test suggestion persistence to database."""
        # Create temporary playbook
        playbook_path = tmp_path / "test.yml"
        playbook_path.write_text("---\n- hosts: all\n  tasks: []\n")

        # Mock ansible-lint output
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout=json.dumps(
                [
                    {
                        "rule": {"id": "no-changed-when"},
                        "message": "Commands should have changed_when",
                        "level": "warning",
                        "location": {"path": str(playbook_path), "lines": {"begin": 6}},
                    }
                ]
            ),
            stderr="",
        )

        # Mock database session
        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()

        analyzer = PlaybookAnalyzer(db_session=mock_session)
        result = await analyzer.analyze_playbook(str(playbook_path), task_id="test-task-id")

        # Verify session.add was called
        assert mock_session.add.call_count == 1
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    async def test_persist_suggestions_no_session(self, mock_run, tmp_path):
        """Test that analyzer works without database session."""
        # Create temporary playbook
        playbook_path = tmp_path / "test.yml"
        playbook_path.write_text("---\n- hosts: all\n  tasks: []\n")

        # Mock ansible-lint output
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout=json.dumps([]),
            stderr="",
        )

        analyzer = PlaybookAnalyzer(db_session=None)
        result = await analyzer.analyze_playbook(str(playbook_path))

        # Should complete successfully without DB session
        assert result.total_issues == 0


class TestInfraAgentAnalyzerIntegration:
    """Test InfraAgent integration with PlaybookAnalyzer."""

    @pytest.mark.asyncio
    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    async def test_analyze_playbook_work_type(self, mock_run, tmp_path):
        """Test analyze_playbook work type handler."""
        from src.agents.infra_agent.agent import InfraAgent
        from src.common.config import Config
        from src.common.protocol import WorkRequest

        # Create temporary playbook
        playbook_path = tmp_path / "test.yml"
        playbook_path.write_text("---\n- hosts: all\n  tasks: []\n")

        # Mock ansible-lint output
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout=json.dumps(
                [
                    {
                        "rule": {"id": "yaml"},
                        "message": "YAML syntax issue",
                        "level": "error",
                        "location": {"path": str(playbook_path), "lines": {"begin": 1}},
                    }
                ]
            ),
            stderr="",
        )

        # Create agent (mock config)
        config = MagicMock(spec=Config)
        config.db_session = None
        agent = InfraAgent(agent_id="test-agent", config=config, repo_path=str(tmp_path))

        # Create work request
        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="analyze_playbook",
            parameters={"playbook_path": str(playbook_path)},
        )

        # Execute work
        result = await agent.execute_work(work_request)

        assert result.status == "completed"
        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert output_data["total_issues"] == 1
        assert "best_practices" in output_data["by_category"]

    @pytest.mark.asyncio
    async def test_analyze_playbook_missing_parameter(self, tmp_path):
        """Test analyze_playbook with missing playbook_path parameter."""
        from src.agents.infra_agent.agent import InfraAgent
        from src.common.config import Config
        from src.common.protocol import WorkRequest

        config = MagicMock(spec=Config)
        config.db_session = None
        agent = InfraAgent(agent_id="test-agent", config=config, repo_path=str(tmp_path))

        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="analyze_playbook",
            parameters={},  # Missing playbook_path
        )

        result = await agent.execute_work(work_request)

        assert result.status == "failed"
        assert result.exit_code == 1
        assert "playbook_path parameter is required" in result.error_message

    @pytest.mark.asyncio
    @patch("src.agents.infra_agent.executor.PlaybookExecutor.execute_playbook")
    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    async def test_run_playbook_triggers_analyzer_on_failure(
        self, mock_lint, mock_executor, tmp_path
    ):
        """Test that run_playbook triggers analyzer when execution fails."""
        from src.agents.infra_agent.agent import InfraAgent
        from src.agents.infra_agent.executor import ExecutionSummary
        from src.common.config import Config
        from src.common.protocol import WorkRequest

        # Create temporary playbook
        playbook_path = tmp_path / "test.yml"
        playbook_path.write_text("---\n- hosts: all\n  tasks: []\n")

        # Mock executor to return failed execution
        mock_executor.return_value = ExecutionSummary(
            status="failed",
            exit_code=2,
            duration_ms=100,
            ok_count=0,
            changed_count=0,
            failed_count=1,
            skipped_count=0,
            unreachable_count=0,
            failed_tasks=["task1"],
            key_errors=["Error executing task"],
            hosts_summary={},
        )

        # Mock ansible-lint output
        mock_lint.return_value = MagicMock(
            returncode=2,
            stdout=json.dumps(
                [
                    {
                        "rule": {"id": "no-changed-when"},
                        "message": "Test",
                        "level": "warning",
                        "location": {"path": str(playbook_path), "lines": {"begin": 1}},
                    }
                ]
            ),
            stderr="",
        )

        config = MagicMock(spec=Config)
        config.db_session = None
        agent = InfraAgent(agent_id="test-agent", config=config, repo_path=str(tmp_path))

        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="run_playbook",
            parameters={"playbook_path": str(playbook_path)},
        )

        result = await agent.execute_work(work_request)

        # Should be failed and include analysis
        assert result.status == "failed"
        assert "improvement suggestions" in result.output
        assert result.analysis_result is not None
        assert result.analysis_result["total_issues"] == 1

    @pytest.mark.asyncio
    @patch("src.agents.infra_agent.executor.PlaybookExecutor.execute_playbook")
    @patch("src.agents.infra_agent.analyzer.subprocess.run")
    @patch("src.agents.infra_agent.task_mapper.TaskMapper.map_task_to_playbook")
    async def test_deploy_service_triggers_analyzer_on_failure(
        self, mock_mapper, mock_lint, mock_executor, tmp_path
    ):
        """Test that deploy_service triggers analyzer when execution fails."""
        from src.agents.infra_agent.agent import InfraAgent
        from src.agents.infra_agent.executor import ExecutionSummary
        from src.agents.infra_agent.task_mapper import MappingResult
        from src.common.config import Config
        from src.common.protocol import WorkRequest

        # Create temporary playbook
        playbook_path = tmp_path / "test.yml"
        playbook_path.write_text("---\n- hosts: all\n  tasks: []\n")

        # Mock task mapper to return playbook match
        mock_mapper.return_value = MappingResult(
            playbook_path=str(playbook_path),
            confidence=0.9,
            method="exact",
            alternatives=[],
            suggestion=None,
        )

        # Mock executor to return failed execution
        mock_executor.return_value = ExecutionSummary(
            status="failed",
            exit_code=2,
            duration_ms=100,
            ok_count=0,
            changed_count=0,
            failed_count=1,
            skipped_count=0,
            unreachable_count=0,
            failed_tasks=["task1"],
            key_errors=["Error executing task"],
            hosts_summary={},
        )

        # Mock ansible-lint output
        mock_lint.return_value = MagicMock(
            returncode=2,
            stdout=json.dumps(
                [
                    {
                        "rule": {"id": "yaml"},
                        "message": "YAML issue",
                        "level": "error",
                        "location": {"path": str(playbook_path), "lines": {"begin": 1}},
                    }
                ]
            ),
            stderr="",
        )

        config = MagicMock(spec=Config)
        config.db_session = None
        agent = InfraAgent(agent_id="test-agent", config=config, repo_path=str(tmp_path))

        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="deploy_service",
            parameters={"task_intent": "deploy kuma"},
        )

        result = await agent.execute_work(work_request)

        # Should be failed and include analysis
        assert result.status == "failed"
        assert "improvement suggestions" in result.output
        assert result.analysis_result is not None
        assert result.analysis_result["total_issues"] == 1
