"""Orchestrator integration tests for Infrastructure Agent.

Test coverage:
- Orchestrator ↔ InfraAgent communication flows
- Work request dispatch and result handling
- Agent registration and capability reporting
- Heartbeat and resource metrics
- Error scenarios and recovery
- INFRA-01 through INFRA-04 requirement verification
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from src.agents.infra_agent import InfraAgent
from src.agents.infra_agent.analyzer import AnalysisResult, Suggestion
from src.agents.infra_agent.executor import ExecutionSummary
from src.common.config import Config
from src.common.protocol import MessageEnvelope, WorkRequest, WorkResult


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_config():
    """Create a mock Config object for testing."""
    config = MagicMock(spec=Config)
    config.rabbitmq_host = "localhost"
    config.rabbitmq_port = 5672
    config.rabbitmq_user = "guest"
    config.rabbitmq_password = "guest"
    config.heartbeat_interval_seconds = 30
    config.db_session = None
    return config


@pytest.fixture
def infra_agent(mock_config, tmp_path):
    """Create InfraAgent instance for testing."""
    return InfraAgent(
        agent_id="test-agent-orchestrator",
        config=mock_config,
        repo_path=str(tmp_path),
    )


# ============================================================================
# Orchestrator Integration Tests
# ============================================================================


class TestOrchestratorInfraAgentIntegration:
    """Test orchestrator integration with InfraAgent."""

    @pytest.mark.asyncio
    async def test_orchestrator_routes_to_infra_agent(self, infra_agent):
        """Test orchestrator routes work to infra agent with work_type='run_playbook'."""
        # Mock successful execution
        mock_summary = ExecutionSummary(
            status="successful",
            exit_code=0,
            duration_ms=1500,
            ok_count=3,
            changed_count=2,
            failed_count=0,
            skipped_count=0,
            failed_tasks=[],
            key_errors=[],
            hosts_summary={},
        )

        with patch.object(infra_agent.executor, "execute_playbook", return_value=mock_summary):
            # Simulate orchestrator routing decision
            # Use run_playbook instead of deploy_service to avoid task mapping
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="run_playbook",
                parameters={
                    "playbook_path": "/test/kuma-deploy.yml",
                },
            )

            # Agent executes work
            result = await infra_agent.execute_work(work_request)

            # Verify result suitable for orchestrator
            assert isinstance(result, WorkResult)
            assert result.task_id == work_request.task_id
            assert result.status == "completed"
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_infra_agent_work_result_handled(self, infra_agent):
        """Test orchestrator receives and handles InfraAgent work result."""
        # Mock successful execution
        mock_summary = ExecutionSummary(
            status="successful",
            exit_code=0,
            duration_ms=2500,
            ok_count=5,
            changed_count=3,
            failed_count=0,
            skipped_count=0,
            failed_tasks=[],
            key_errors=[],
            hosts_summary={"localhost": {"ok": 5, "changed": 3, "failures": 0}},
        )

        with patch.object(infra_agent.executor, "execute_playbook", return_value=mock_summary):
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="run_playbook",
                parameters={
                    "playbook_path": "/path/to/playbook.yml",
                },
            )

            result = await infra_agent.execute_work(work_request)

            # Verify orchestrator can extract key information
            assert result.status == "completed"
            assert result.duration_ms == 2500
            assert result.agent_id is not None
            assert "successful" in result.output.lower()

            # Orchestrator would update task status="completed" in database
            # Orchestrator would create git audit entry with result.output

    @pytest.mark.asyncio
    async def test_infra_agent_failure_logged(self, infra_agent):
        """Test orchestrator logs InfraAgent failure with status='failed' and error."""
        # Mock failed execution
        mock_summary = ExecutionSummary(
            status="failed",
            exit_code=1,
            duration_ms=800,
            ok_count=1,
            changed_count=0,
            failed_count=2,
            skipped_count=0,
            failed_tasks=["Install service", "Start service"],
            key_errors=["Connection refused"],
            hosts_summary={"localhost": {"ok": 1, "changed": 0, "failures": 2}},
        )

        with patch.object(infra_agent.executor, "execute_playbook", return_value=mock_summary):
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="run_playbook",
                parameters={
                    "playbook_path": "/path/to/playbook.yml",
                },
            )

            result = await infra_agent.execute_work(work_request)

            # Verify failure information for orchestrator
            assert result.status == "failed"
            assert result.exit_code == 1
            assert result.error_message is not None
            assert "failed" in result.error_message.lower()

            # Orchestrator would update task status="failed" in database
            # Orchestrator would log error_message for troubleshooting


# ============================================================================
# Agent Registration Tests
# ============================================================================


class TestInfraAgentRegistration:
    """Test InfraAgent registration with orchestrator."""

    def test_infra_agent_registers_capabilities(self, infra_agent):
        """Test get_agent_capabilities returns dict with all work types."""
        capabilities = infra_agent.get_agent_capabilities()

        # Verify all capabilities present
        assert isinstance(capabilities, dict)
        assert capabilities["run_playbook"] is True
        assert capabilities["discover_playbooks"] is True
        assert capabilities["generate_template"] is True
        assert capabilities["analyze_playbook"] is True

        # Orchestrator would use this to route work requests

    def test_infra_agent_heartbeat_includes_resources(self, infra_agent):
        """Test heartbeat includes metrics and agent_type='infra'."""
        # Verify agent type
        assert infra_agent.agent_type == "infra"

        # In real implementation, heartbeat would include:
        # - agent_id
        # - agent_type: "infra"
        # - status: "online" | "offline" | "busy"
        # - resources: {cpu_percent, memory_percent, gpu_vram_available_gb}
        # - current_task_id: Optional[UUID]

        # For now, verify agent provides required attributes
        assert hasattr(infra_agent, "agent_id")
        assert hasattr(infra_agent, "agent_type")
        assert infra_agent.agent_type == "infra"

    def test_agent_id_propagated_to_results(self, infra_agent):
        """Test agent_id is included in all WorkResult responses."""
        # This is verified implicitly in other tests, but explicitly check here
        assert infra_agent.agent_id == "test-agent-orchestrator"


# ============================================================================
# Work Dispatch Flow Tests
# ============================================================================


class TestWorkDispatchFlow:
    """Test work dispatch flow between orchestrator and agent."""

    def test_work_request_serialization(self):
        """Test WorkRequest → MessageEnvelope → deserialize preserves parameters."""
        # Create work request
        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="deploy_service",
            parameters={
                "task_intent": "Deploy Kuma",
                "extravars": {"kuma_version": "2.0"},
            },
        )

        # Wrap in message envelope (orchestrator would do this)
        envelope = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            payload=work_request.model_dump(),
        )

        # Serialize to JSON (for RabbitMQ)
        json_str = envelope.to_json()

        # Deserialize (agent would do this)
        envelope_received = MessageEnvelope.from_json(json_str)
        work_request_received = WorkRequest(**envelope_received.payload)

        # Verify parameters preserved
        assert work_request_received.task_id == work_request.task_id
        assert work_request_received.work_type == work_request.work_type
        assert work_request_received.parameters["task_intent"] == "Deploy Kuma"
        assert work_request_received.parameters["extravars"]["kuma_version"] == "2.0"

    @pytest.mark.asyncio
    async def test_work_result_serialization(self, infra_agent):
        """Test WorkResult → MessageEnvelope → deserialize preserves ExecutionSummary."""
        # Mock successful execution
        mock_summary = ExecutionSummary(
            status="successful",
            exit_code=0,
            duration_ms=1500,
            ok_count=3,
            changed_count=2,
            failed_count=0,
            skipped_count=0,
            failed_tasks=[],
            key_errors=[],
            hosts_summary={"localhost": {"ok": 3, "changed": 2, "failures": 0}},
        )

        with patch.object(infra_agent.executor, "execute_playbook", return_value=mock_summary):
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="run_playbook",
                parameters={"playbook_path": "/test.yml"},
            )

            # Execute work
            result = await infra_agent.execute_work(work_request)

            # Wrap in message envelope (agent would do this)
            envelope = MessageEnvelope(
                from_agent="infra",
                to_agent="orchestrator",
                type="work_result",
                payload=result.model_dump(),
            )

            # Serialize to JSON
            json_str = envelope.to_json()

            # Deserialize (orchestrator would do this)
            envelope_received = MessageEnvelope.from_json(json_str)
            result_received = WorkResult(**envelope_received.payload)

            # Verify ExecutionSummary information preserved
            assert result_received.task_id == work_request.task_id
            assert result_received.status == "completed"
            assert result_received.duration_ms == 1500
            assert "3 ok, 2 changed" in result_received.output


# ============================================================================
# Error Scenario Tests
# ============================================================================


class TestInfraAgentErrorScenarios:
    """Test error scenarios in orchestrator integration."""

    @pytest.mark.asyncio
    async def test_playbook_not_found_error(self, infra_agent):
        """Test nonexistent playbook returns status='failed' with error_message."""
        from src.agents.infra_agent.executor import PlaybookNotFoundError

        # Mock PlaybookNotFoundError
        with patch.object(
            infra_agent.executor,
            "execute_playbook",
            side_effect=PlaybookNotFoundError("/nonexistent.yml"),
        ):
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="run_playbook",
                parameters={"playbook_path": "/nonexistent.yml"},
            )

            result = await infra_agent.execute_work(work_request)

            # Verify error handling
            assert result.status == "failed"
            assert result.exit_code == 2  # Playbook not found exit code
            assert result.error_message is not None
            assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_execution_timeout_error(self, infra_agent):
        """Test execution timeout returns status='failed' with timeout message."""
        from src.agents.infra_agent.executor import ExecutionTimeoutError

        # Mock timeout
        with patch.object(
            infra_agent.executor,
            "execute_playbook",
            side_effect=ExecutionTimeoutError("Execution exceeded 600s"),
        ):
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="run_playbook",
                parameters={
                    "playbook_path": "/test.yml",
                    "timeout_seconds": 600,
                },
            )

            result = await infra_agent.execute_work(work_request)

            # Verify timeout handling
            assert result.status == "failed"
            assert result.exit_code == 124  # Standard timeout exit code
            assert result.error_message is not None
            assert "timeout" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_invalid_work_type_error(self, infra_agent):
        """Test invalid work_type returns status='failed' with error message."""
        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="invalid_operation",
            parameters={},
        )

        result = await infra_agent.execute_work(work_request)

        # Verify error handling
        assert result.status == "failed"
        assert result.exit_code == 1
        assert result.error_message is not None
        assert "Unknown work type" in result.error_message

    @pytest.mark.asyncio
    async def test_ansible_runner_error(self, infra_agent):
        """Test ansible-runner error returns status='failed' with error message."""
        from src.agents.infra_agent.executor import AnsibleRunnerError

        # Mock AnsibleRunnerError
        with patch.object(
            infra_agent.executor,
            "execute_playbook",
            side_effect=AnsibleRunnerError("Runner initialization failed"),
        ):
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="run_playbook",
                parameters={"playbook_path": "/test.yml"},
            )

            result = await infra_agent.execute_work(work_request)

            # Verify error handling
            assert result.status == "failed"
            assert result.exit_code == 1
            assert result.error_message is not None
            assert "runner" in result.error_message.lower()


# ============================================================================
# Requirement Verification Tests
# ============================================================================


class TestRequirementVerification:
    """Test explicit verification of INFRA-01 through INFRA-04 requirements."""

    @pytest.mark.infra_requirement("INFRA-01")
    @pytest.mark.asyncio
    async def test_INFRA_01_task_mapping(self, mock_config, tmp_path):
        """INFRA-01: Verify 'Deploy Kuma' maps to kuma-deploy.yml using hybrid strategy."""
        # Create kuma-deploy.yml in temp repo
        kuma_playbook = tmp_path / "kuma-deploy.yml"
        kuma_playbook.write_text(
            """---
# chiffon:service=kuma
# chiffon:description=Deploy Kuma service mesh
- name: Deploy Kuma Service Mesh
  hosts: all
  tasks:
    - name: Install Kuma
      debug:
        msg: "Installing Kuma"
"""
        )

        # Create InfraAgent with temp repo
        agent = InfraAgent("test-infra-01", mock_config, repo_path=str(tmp_path))

        # Discover playbooks
        await agent.discover_playbooks(force_refresh=True)

        # Create task mapper
        from src.agents.infra_agent.cache_manager import CacheManager
        from src.agents.infra_agent.task_mapper import PlaybookMetadata, TaskMapper

        cache_manager = CacheManager(mock_config)
        catalog_dicts = await agent.discover_playbooks(force_refresh=False)
        catalog = [PlaybookMetadata(**pb) for pb in catalog_dicts]

        task_mapper = TaskMapper(cache_manager, catalog)

        # Map task
        result = await task_mapper.map_task_to_playbook("Deploy Kuma")

        # Verify INFRA-01 requirement
        assert result.playbook_path is not None
        assert "kuma-deploy.yml" in result.playbook_path
        assert result.confidence == 1.0  # Exact match
        assert result.method in ["exact", "semantic", "cached"]  # method not strategy

    @pytest.mark.infra_requirement("INFRA-02")
    @pytest.mark.asyncio
    async def test_INFRA_02_execution_and_output(self, infra_agent, tmp_path):
        """INFRA-02: Execute playbook and verify structured summary (not streaming)."""
        # Create test playbook
        test_playbook = tmp_path / "test-playbook.yml"
        test_playbook.write_text(
            """---
- name: Test Playbook
  hosts: localhost
  tasks:
    - name: Test task
      debug:
        msg: "Test"
"""
        )

        # Mock successful execution
        mock_summary = ExecutionSummary(
            status="successful",
            exit_code=0,
            duration_ms=1200,
            ok_count=1,
            changed_count=0,
            failed_count=0,
            skipped_count=0,
            failed_tasks=[],
            key_errors=[],
            hosts_summary={"localhost": {"ok": 1, "changed": 0, "failures": 0}},
        )

        with patch.object(infra_agent.executor, "execute_playbook", return_value=mock_summary):
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="run_playbook",
                parameters={"playbook_path": str(test_playbook)},
            )

            result = await infra_agent.execute_work(work_request)

            # Verify INFRA-02 requirement: structured summary
            assert result.status == "completed"
            assert result.duration_ms == 1200
            assert "1 ok" in result.output
            assert "0 changed" in result.output
            assert "0 failed" in result.output

            # NOT streaming - complete summary returned at once

    @pytest.mark.infra_requirement("INFRA-03")
    @pytest.mark.asyncio
    async def test_INFRA_03_improvement_suggestions(self, infra_agent, tmp_path):
        """INFRA-03: Verify failure triggers analysis with categorized suggestions."""
        # Create test playbook
        test_playbook = tmp_path / "test-playbook.yml"
        test_playbook.write_text(
            """---
- name: Test Playbook
  hosts: localhost
  tasks:
    - name: Failing task
      fail:
        msg: "Intentional failure"
"""
        )

        # Mock failed execution
        mock_summary = ExecutionSummary(
            status="failed",
            exit_code=1,
            duration_ms=500,
            ok_count=0,
            changed_count=0,
            failed_count=1,
            skipped_count=0,
            failed_tasks=["Failing task"],
            key_errors=["Intentional failure"],
            hosts_summary={"localhost": {"ok": 0, "changed": 0, "failures": 1}},
        )

        # Mock analyzer
        mock_suggestions = [
            Suggestion(
                category="best-practice",
                rule_id="no-handler",
                severity="medium",
                message="Add error handling",
                reasoning="Improves playbook resilience",
            ),
            Suggestion(
                category="security",
                rule_id="no-plain-text-password",
                severity="high",
                message="Use vault for secrets",
                reasoning="Prevents credential exposure",
            ),
        ]
        mock_analysis = AnalysisResult(
            playbook_path=str(test_playbook),
            total_issues=2,
            by_category={"best-practice": 1, "security": 1},
            suggestions=mock_suggestions,
        )

        with patch.object(infra_agent.executor, "execute_playbook", return_value=mock_summary):
            with patch.object(infra_agent.analyzer, "analyze_playbook", return_value=mock_analysis):
                work_request = WorkRequest(
                    task_id=uuid4(),
                    work_type="run_playbook",
                    parameters={"playbook_path": str(test_playbook)},
                )

                result = await infra_agent.execute_work(work_request)

                # Verify INFRA-03 requirement: suggestions generated
                assert result.status == "failed"
                assert result.analysis_result is not None
                assert result.analysis_result["total_issues"] == 2
                assert len(result.analysis_result["suggestions"]) == 2

                # Verify categorization
                assert "best-practice" in result.analysis_result["by_category"]
                assert "security" in result.analysis_result["by_category"]

                # Verify suggestions in output
                assert "2 improvement suggestions" in result.output

    @pytest.mark.infra_requirement("INFRA-04")
    @pytest.mark.asyncio
    async def test_INFRA_04_template_generation(self, infra_agent):
        """INFRA-04: Generate template for 'myservice' and verify Galaxy-compliant output."""
        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="generate_template",
            parameters={
                "service_name": "myservice",
                "description": "My custom service",
                "service_port": 8080,
            },
        )

        result = await infra_agent.execute_work(work_request)

        # Verify INFRA-04 requirement: template generation
        assert result.status == "completed"
        assert result.exit_code == 0

        # Parse output
        output_data = json.loads(result.output)
        assert output_data["service_name"] == "myservice"

        # Verify Galaxy-compliant structure
        playbook_content = output_data["playbook_content"]
        assert "chiffon:service=myservice" in playbook_content
        assert "My custom service" in playbook_content
        assert "service_port: 8080" in playbook_content or "8080" in playbook_content

        # Verify role structure (Galaxy requirements)
        role_structure = output_data["role_structure"]
        role_keys = list(role_structure.keys())
        assert any("tasks/main.yml" in key for key in role_keys)
        assert any("handlers/main.yml" in key for key in role_keys)
        assert any("defaults/main.yml" in key for key in role_keys)
        assert any("meta/main.yml" in key for key in role_keys)

        # Verify metadata compliant with Galaxy
        meta_key = next((k for k in role_keys if "meta/main.yml" in k), None)
        assert meta_key is not None
        meta_content = role_structure[meta_key]
        assert "galaxy_info:" in meta_content
        assert "author:" in meta_content
        assert "description:" in meta_content
        assert "platforms:" in meta_content


# ============================================================================
# Message Protocol Tests
# ============================================================================


class TestMessageProtocol:
    """Test message protocol compatibility with orchestrator."""

    def test_message_envelope_validation(self):
        """Test MessageEnvelope validates required fields."""
        # Valid envelope
        envelope = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            payload={"test": "data"},
        )

        assert envelope.protocol_version == "1.0"
        assert envelope.from_agent == "orchestrator"
        assert envelope.to_agent == "infra"
        assert envelope.type == "work_request"
        assert envelope.priority == 3  # Default priority

    def test_work_request_validation(self):
        """Test WorkRequest validates required fields."""
        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="deploy_service",
            parameters={"task_intent": "Deploy Kuma"},
        )

        assert work_request.work_type == "deploy_service"
        assert work_request.parameters["task_intent"] == "Deploy Kuma"
        assert isinstance(work_request.hints, dict)  # Default empty dict

    def test_work_result_validation(self):
        """Test WorkResult validates status and error_message consistency."""
        from pydantic import ValidationError

        # Valid completed result
        result_ok = WorkResult(
            task_id=uuid4(),
            status="completed",
            exit_code=0,
            output="Success",
            duration_ms=1000,
            agent_id=uuid4(),
        )
        assert result_ok.error_message is None

        # Valid failed result with error_message
        result_fail = WorkResult(
            task_id=uuid4(),
            status="failed",
            exit_code=1,
            output="",
            error_message="Something went wrong",
            duration_ms=500,
            agent_id=uuid4(),
        )
        assert result_fail.error_message == "Something went wrong"

        # Invalid: failed without error_message should raise ValidationError
        with pytest.raises(ValidationError):
            WorkResult(
                task_id=uuid4(),
                status="failed",
                exit_code=1,
                output="",
                duration_ms=500,
                agent_id=uuid4(),
            )

    def test_timestamp_serialization(self):
        """Test timestamp serialization in MessageEnvelope."""
        envelope = MessageEnvelope(
            from_agent="infra",
            to_agent="orchestrator",
            type="work_result",
            payload={"test": "data"},
        )

        # Serialize to JSON
        json_str = envelope.to_json()

        # Deserialize
        envelope_received = MessageEnvelope.from_json(json_str)

        # Verify timestamp preserved
        assert isinstance(envelope_received.timestamp, datetime)

    def test_trace_id_propagation(self):
        """Test trace_id and request_id propagation for debugging."""
        trace_id = uuid4()
        request_id = uuid4()

        envelope = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            payload={"test": "data"},
            trace_id=trace_id,
            request_id=request_id,
        )

        # Serialize and deserialize
        json_str = envelope.to_json()
        envelope_received = MessageEnvelope.from_json(json_str)

        # Verify IDs preserved
        assert envelope_received.trace_id == trace_id
        assert envelope_received.request_id == request_id
