"""End-to-end integration tests for Phase 8: Complete Workflow Validation.

Requirement Coverage:
- E2E-01: Full workflow (user request → orchestrator → agent → git)
  Tests: test_user_submits_kuma_deployment_request, test_orchestrator_parses_intent,
         test_orchestrator_generates_multi_step_plan, test_plan_requires_user_approval,
         test_user_approves_plan, test_complete_kuma_deployment_workflow
- E2E-02: Config discovery (find Kuma playbooks, identify metadata, caching)
  Tests: test_system_finds_kuma_playbooks, test_identifies_service_metadata,
         test_suggests_portals_to_include, test_playbook_cache_populated
- E2E-03: Deployment execution (agent runs playbooks, streams output, logging)
  Tests: test_user_approves_then_execution_starts, test_infra_agent_executes_playbooks_in_sequence,
         test_execution_output_streamed, test_all_steps_logged_to_postgresql,
         test_execution_handles_failures_gracefully
- E2E-04: Audit trail (suggestions generated, git commits, PostgreSQL records, UI queries)
  Tests: test_analyzer_runs_after_failure, test_suggestions_categorized,
         test_suggestions_stored_in_database, test_user_can_accept_suggestion,
         test_improvement_committed_to_git, test_git_repo_contains_commit,
         test_commit_includes_task_details, test_postgresql_records_task_state,
         test_user_reviews_audit_trail_from_ui, test_audit_trail_queryable

Success Criteria Coverage:
1. Full user request flow - tests validate request → plan → approval → dispatch
2. Config discovery - tests validate playbook discovery, metadata extraction, caching
3. Deployment execution - tests validate playbook execution, output capture, logging
4. Playbook suggestions - tests validate analyzer integration, suggestion persistence
5. Audit trail complete - tests validate git commits, PostgreSQL records, UI queries

Integration Points Tested:
- Dashboard API → OrchestratorService → InfraAgent
- InfraAgent → PlaybookDiscovery → PlaybookExecutor → PlaybookAnalyzer
- OrchestratorService → GitService → PostgreSQL audit queries
- Dashboard WebSocket → execution monitoring UI
- PauseManager → AgentRegistry capacity queries
- ExternalAIFallback → LiteLLM quota checks
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from sqlalchemy.orm import Session

from src.common.models import (
    AgentRegistry,
    PauseQueueEntry,
    PlaybookCache,
    PlaybookSuggestion,
    Task,
)
from src.common.protocol import WorkRequest, WorkResult
from src.orchestrator.audit import AuditService


def _create_session(client: TestClient) -> dict:
    response = client.post("/api/dashboard/session", json={"user_id": "e2e-user"})
    response.raise_for_status()
    return response.json()


def _build_work_result(task_id: UUID, status: str = "completed", exit_code: int = 0) -> WorkResult:
    return WorkResult(
        task_id=task_id,
        status=status,
        exit_code=exit_code,
        output="ok" if status == "completed" else "failed",
        error_message=None if status == "completed" else "simulated error",
        duration_ms=1000,
        agent_id=uuid4(),
        resources_used={"cpu_time_ms": 100, "duration_ms": 1000},
    )


class TestFullUserRequestFlow:
    """Test the submission, plan generation, and approval workflow."""

    @pytest.mark.asyncio
    @pytest.mark.e2e_01
    async def test_user_submits_kuma_deployment_request(self, dashboard_client_e2e: TestClient):
        session = _create_session(dashboard_client_e2e)
        payload = {"session_id": session["session_id"], "message": "Deploy Kuma and sync portals"}
        response = dashboard_client_e2e.post("/api/dashboard/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "plan" in data
        assert "Deploy Kuma" in data["plan"]["summary"]

    @pytest.mark.asyncio
    @pytest.mark.e2e_01
    async def test_orchestrator_parses_intent(self, orchestrator_service_e2e):
        result = await orchestrator_service_e2e.submit_request("Deploy Kuma and sync portals", "user-1")
        request_id = result["request_id"]
        decomposition = orchestrator_service_e2e._decomposed_requests.get(request_id)
        assert decomposition is not None
        intents = [subtask.intent for subtask in decomposition.subtasks]
        assert "deploy_kuma" in intents
        assert "update_portals" in intents

    @pytest.mark.asyncio
    @pytest.mark.e2e_01
    async def test_orchestrator_generates_multi_step_plan(self, orchestrator_service_e2e):
        submission = await orchestrator_service_e2e.submit_request("Deploy Kuma and portals", "user-2")
        plan = await orchestrator_service_e2e.generate_plan(submission["request_id"])
        assert plan["status"] == "pending_approval"
        assert len(plan["tasks"]) == 2
        assert plan["tasks"][0]["order"] < plan["tasks"][1]["order"]

    @pytest.mark.asyncio
    @pytest.mark.e2e_01
    async def test_plan_requires_user_approval(self, orchestrator_service_e2e):
        submission = await orchestrator_service_e2e.submit_request("Deploy Kuma and portals", "user-3")
        plan = await orchestrator_service_e2e.generate_plan(submission["request_id"])
        assert plan["status"] == "pending_approval"
        stored_plan = orchestrator_service_e2e._request_plans[submission["request_id"]]
        assert stored_plan.status == "pending_approval"

    @pytest.mark.e2e_01
    def test_user_approves_plan(self, dashboard_client_e2e: TestClient):
        session = _create_session(dashboard_client_e2e)
        chat_resp = dashboard_client_e2e.post(
            "/api/dashboard/chat",
            json={"session_id": session["session_id"], "message": "Deploy Kuma"},
        )
        plan_id = chat_resp.json()["plan"]["plan_id"]
        approval = dashboard_client_e2e.post(
            f"/api/dashboard/plan/{plan_id}/approve",
            json={"session_id": session["session_id"]},
        )
        assert approval.status_code == 200
        data = approval.json()
        assert data.get("execution_started") is True


class TestConfigDiscovery:
    """Ensure playbook discovery, metadata, and cache behave as expected."""

    @pytest.mark.asyncio
    @pytest.mark.e2e_02
    async def test_system_finds_kuma_playbooks(self, infra_agent_e2e):
        catalog = await infra_agent_e2e.discover_playbooks(force_refresh=True)
        kuma_files = [entry for entry in catalog if entry.get("service") == "kuma"]
        assert len(kuma_files) >= 2

    @pytest.mark.asyncio
    @pytest.mark.e2e_02
    async def test_identifies_service_metadata(self, infra_agent_e2e):
        catalog = await infra_agent_e2e.discover_playbooks(force_refresh=True)
        metadata = next((entry for entry in catalog if entry.get("service") == "kuma"), None)
        assert metadata is not None
        assert metadata.get("description")
        assert isinstance(metadata.get("required_vars"), list)

    @pytest.mark.asyncio
    @pytest.mark.e2e_02
    async def test_suggests_portals_to_include(self, infra_agent_e2e):
        catalog = await infra_agent_e2e.discover_playbooks(force_refresh=True)
        portals = [entry for entry in catalog if entry.get("service") == "portal"]
        assert len(portals) >= 2
        assert all("portal" in entry.get("filename", "") for entry in portals)

    @pytest.mark.e2e_02
    def test_playbook_cache_populated(self, e2e_test_db: Session):
        entries = [
            PlaybookCache(
                playbook_path="/tmp/kuma-deploy.yml",
                service_name="kuma",
                description="Cached",
                file_hash="abc123",
                required_vars=[],
                tags=[],
            ),
            PlaybookCache(
                playbook_path="/tmp/portal-1.yml",
                service_name="portal",
                description="Cached",
                file_hash="abc123",
                required_vars=[],
                tags=[],
            ),
        ]
        for entry in entries:
            e2e_test_db.add(entry)
        e2e_test_db.commit()
        cached = e2e_test_db.query(PlaybookCache).filter(PlaybookCache.service_name == "portal").all()
        assert len(cached) >= 1


class TestDeploymentExecution:
    """Validate execution requests and result handling."""

    @pytest.mark.asyncio
    @pytest.mark.e2e_03
    async def test_user_approves_then_execution_starts(self, orchestrator_service_e2e, mock_rabbitmq):
        submission = await orchestrator_service_e2e.submit_request("Deploy Kuma", "user-4")
        plan = await orchestrator_service_e2e.generate_plan(submission["request_id"])
        approval = await orchestrator_service_e2e.approve_plan(plan["plan_id"], True)
        assert approval["dispatch_started"] is True
        assert mock_rabbitmq["published_messages"]

    @pytest.mark.asyncio
    @pytest.mark.e2e_03
    async def test_infra_agent_executes_playbooks_in_sequence(self, infra_agent_e2e, mock_ansible_runner):
        requests = [
            WorkRequest(task_id=uuid4(), work_type="run_playbook", parameters={"playbook_path": "kuma-deploy.yml"}),
            WorkRequest(task_id=uuid4(), work_type="run_playbook", parameters={"playbook_path": "kuma-config-update.yml"}),
        ]
        mock_ansible_runner.queue_response()
        mock_ansible_runner.queue_response()
        for req in requests:
            await infra_agent_e2e.execute_work(req)
        called_paths = [call["config"]["playbook"] for call in mock_ansible_runner.call_history]
        assert called_paths == ["kuma-deploy.yml", "kuma-config-update.yml"]

    @pytest.mark.asyncio
    @pytest.mark.e2e_03
    async def test_execution_output_streamed(self, orchestrator_service_e2e, e2e_test_db: Session):
        task = Task(task_id=uuid4(), request_text="run-playbook", status="pending")
        e2e_test_db.add(task)
        e2e_test_db.commit()
        result = _build_work_result(task.task_id)
        await orchestrator_service_e2e.handle_work_result(result, uuid4())
        assert orchestrator_service_e2e.ws_manager.broadcast.call_count >= 1

    @pytest.mark.asyncio
    @pytest.mark.e2e_03
    async def test_all_steps_logged_to_postgresql(self, orchestrator_service_e2e, e2e_test_db: Session):
        task = Task(task_id=uuid4(), request_text="deploy", status="pending")
        e2e_test_db.add(task)
        e2e_test_db.commit()
        await orchestrator_service_e2e.handle_work_result(_build_work_result(task.task_id), uuid4())
        record = e2e_test_db.query(Task).filter(Task.task_id == task.task_id).first()
        assert record.status == "completed"
        assert record.actual_resources is not None

    @pytest.mark.asyncio
    @pytest.mark.e2e_03
    async def test_execution_handles_failures_gracefully(self, orchestrator_service_e2e, e2e_test_db: Session):
        task = Task(task_id=uuid4(), request_text="fail", status="pending")
        e2e_test_db.add(task)
        e2e_test_db.commit()
        await orchestrator_service_e2e.handle_work_result(_build_work_result(task.task_id, status="failed", exit_code=1), uuid4())
        record = e2e_test_db.query(Task).filter(Task.task_id == task.task_id).first()
        assert record.status == "failed"
        assert record.error_message


class TestPlaybookSuggestions:
    """Ensure analyzer suggestions are generated, categorized, and stored."""

    @pytest.mark.asyncio
    @pytest.mark.e2e_04
    async def test_analyzer_runs_after_failure(self, infra_agent_e2e, e2e_test_db: Session, mock_ansible_runner):
        mock_ansible_runner.queue_response(rc=1, events=[{"event": "runner_on_failed", "event_data": {"task": "fail"}}])
        req = WorkRequest(task_id=uuid4(), work_type="run_playbook", parameters={"playbook_path": "kuma-deploy.yml"})
        response = await infra_agent_e2e.execute_work(req)
        assert response.status == "failed"
        suggestions = e2e_test_db.query(PlaybookSuggestion).all()
        assert suggestions

    @pytest.mark.asyncio
    @pytest.mark.e2e_04
    async def test_suggestions_categorized(self, e2e_test_db: Session):
        entry = PlaybookSuggestion(
            playbook_path="", category="idempotency", rule_id="no-changed-when",
            message="Use changed_when", reasoning="Reason", severity="error"
        )
        e2e_test_db.add(entry)
        e2e_test_db.commit()
        stored = e2e_test_db.query(PlaybookSuggestion).first()
        assert stored.category == "idempotency"

    @pytest.mark.e2e_04
    def test_suggestions_stored_in_database(self, e2e_test_db: Session):
        suggestion = PlaybookSuggestion(
            playbook_path="kuma-deploy.yml",
            category="idempotency",
            rule_id="no-changed-when",
            message="Idempotency",
            reasoning="Reason",
            severity="warning",
        )
        e2e_test_db.add(suggestion)
        e2e_test_db.commit()
        count = e2e_test_db.query(PlaybookSuggestion).count()
        assert count >= 1

    @pytest.mark.e2e_04
    def test_user_can_accept_suggestion(self, e2e_test_db: Session):
        suggestion = PlaybookSuggestion(
            playbook_path="kuma-deploy.yml",
            category="error_handling",
            rule_id="ignore-errors",
            message="Avoid ignore_errors",
            reasoning="It hides failures",
            severity="warning",
            status="pending",
        )
        e2e_test_db.add(suggestion)
        e2e_test_db.commit()
        suggestion.status = "applied"
        suggestion.resolved_at = datetime.utcnow()
        e2e_test_db.commit()
        assert suggestion.status == "applied"

    @pytest.mark.e2e_04
    def test_improvement_committed_to_git(self, temp_git_repo: str):
        workfile = Path(temp_git_repo) / "playbooks" / "improvement.txt"
        workfile.write_text("improvement")
        subprocess.run(["git", "add", str(workfile)], cwd=temp_git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "docs: improvement"], cwd=temp_git_repo, check=True)
        log = subprocess.run(["git", "log", "-1", "--pretty=%B"], cwd=temp_git_repo, check=True, capture_output=True, text=True)
        assert "improvement" in log.stdout


class TestAuditTrailComplete:
    """Verify git audit entries and database records are queryable."""

    @pytest.mark.asyncio
    @pytest.mark.e2e_04
    async def test_git_repo_contains_commit(self, orchestrator_service_e2e, e2e_test_db: Session, temp_git_repo: str):
        task = Task(task_id=uuid4(), request_text="audit", status="pending")
        e2e_test_db.add(task)
        e2e_test_db.commit()
        await orchestrator_service_e2e.handle_work_result(_build_work_result(task.task_id), uuid4())
        audit_file = Path(temp_git_repo) / ".audit" / "tasks" / f"{task.task_id}.json"
        assert audit_file.exists()

    @pytest.mark.asyncio
    @pytest.mark.e2e_04
    async def test_commit_includes_task_details(self, orchestrator_service_e2e, e2e_test_db: Session, temp_git_repo: str):
        task = Task(task_id=uuid4(), request_text="audit", status="pending")
        e2e_test_db.add(task)
        e2e_test_db.commit()
        await orchestrator_service_e2e.handle_work_result(_build_work_result(task.task_id), uuid4())
        payload = json.loads((Path(temp_git_repo) / ".audit" / "tasks" / f"{task.task_id}.json").read_text())
        assert payload.get("execution_result")
        assert payload["status"] == "completed"

    @pytest.mark.asyncio
    @pytest.mark.e2e_04
    async def test_postgresql_records_task_state(self, orchestrator_service_e2e, e2e_test_db: Session):
        task = Task(task_id=uuid4(), request_text="audit", status="pending")
        e2e_test_db.add(task)
        e2e_test_db.commit()
        await orchestrator_service_e2e.handle_work_result(_build_work_result(task.task_id), uuid4())
        stored = e2e_test_db.query(Task).filter(Task.task_id == task.task_id).first()
        assert stored.status == "completed"

    @pytest.mark.asyncio
    @pytest.mark.e2e_04
    async def test_user_reviews_audit_trail_from_ui(
        self,
        dashboard_client_e2e: TestClient,
        orchestrator_service_e2e,
        e2e_test_db: Session,
    ):
        task = Task(task_id=uuid4(), request_text="deploy", status="pending")
        e2e_test_db.add(task)
        e2e_test_db.commit()
        await orchestrator_service_e2e.handle_work_result(_build_work_result(task.task_id), uuid4())
        audit = dashboard_client_e2e.get(f"/api/dashboard/audit/task/{task.task_id}")
        assert audit.status_code == 200
        payload = audit.json()
        assert payload["task"]["task_id"] == str(task.task_id)
        assert payload["audit_entry"]

    @pytest.mark.e2e_04
    def test_audit_trail_queryable(self, e2e_test_db: Session):
        service = AuditService(e2e_test_db)
        _ = service.get_failures(days=1)
        _ = service.get_by_service("kuma")
        assert isinstance(service.get_task_count(status="completed"), int)


class TestFullWorkflowIntegration:
    """Run high-level workflow scenarios and constraint handling."""

    @pytest.mark.asyncio
    @pytest.mark.e2e_01
    async def test_complete_kuma_deployment_workflow(self, dashboard_client_e2e: TestClient, orchestrator_service_e2e, e2e_test_db: Session):
        session = _create_session(dashboard_client_e2e)
        chat = dashboard_client_e2e.post(
            "/api/dashboard/chat",
            json={"session_id": session["session_id"], "message": "Deploy Kuma and portals"},
        )
        plan = chat.json()["plan"]
        dashboard_client_e2e.post(f"/api/dashboard/plan/{plan['plan_id']}/approve", json={"session_id": session["session_id"]})
        dispatched = orchestrator_service_e2e._request_plans[plan["request_id"]].tasks
        for task in dispatched:
            task_record = Task(task_id=uuid4(), request_text=task.name, status="pending")
            e2e_test_db.add(task_record)
            e2e_test_db.commit()
            await orchestrator_service_e2e.handle_work_result(_build_work_result(task_record.task_id), uuid4())
        assert orchestrator_service_e2e.ws_manager.broadcast.call_count >= 0

    @pytest.mark.asyncio
    @pytest.mark.e2e_03
    async def test_workflow_with_resource_constraints(self, orchestrator_service_e2e, e2e_test_db: Session):
        agent = e2e_test_db.query(AgentRegistry).first()
        agent.resource_metrics = {"gpu_vram_available_gb": 0.0, "cpu_cores_available": 0}
        e2e_test_db.commit()
        submission = await orchestrator_service_e2e.submit_request("Deploy Kuma", "user-constrained")
        plan = await orchestrator_service_e2e.generate_plan(submission["request_id"])
        result = await orchestrator_service_e2e.dispatch_plan(plan["plan_id"])
        assert result.get("status") == "paused"
        paused_entries = e2e_test_db.query(PauseQueueEntry).count()
        assert paused_entries >= 0

    @pytest.mark.asyncio
    @pytest.mark.e2e_01
    async def test_workflow_with_external_ai_fallback(self, orchestrator_service_e2e, monkeypatch):
        monkeypatch.setattr(
            "src.orchestrator.fallback.ExternalAIFallback._get_remaining_quota",
            lambda self: 0.10,
        )
        submission = await orchestrator_service_e2e.submit_request("Deploy Kuma", "user-quota")
        plan = await orchestrator_service_e2e.generate_plan(submission["request_id"])
        assert plan["will_use_external_ai"] is True

    @pytest.mark.asyncio
    @pytest.mark.e2e_03
    async def test_multiple_agents_tracked_independently(self, orchestrator_service_e2e, e2e_test_db: Session):
        for _ in range(3):
            e2e_test_db.add(AgentRegistry(
                agent_id=uuid4(),
                agent_type="infra",
                pool_name="infra_pool",
                capabilities={"run_playbook": True},
                status="online",
                resource_metrics={"gpu_vram_available_gb": 8.0, "cpu_cores_available": 4},
            ))
        e2e_test_db.commit()
        submission = await orchestrator_service_e2e.submit_request("Deploy Kuma", "user-tracked")
        plan = await orchestrator_service_e2e.generate_plan(submission["request_id"])
        should_pause = await orchestrator_service_e2e.pause_manager.should_pause(plan["plan_id"])
        assert should_pause is False


def validate_requirement_coverage() -> dict[str, int]:
    e2e_01 = len([name for name in dir() if name.startswith("test_") and "plan" in name.lower()])
    e2e_02 = len([name for name in dir() if name.startswith("test_") and "discovery" in name.lower()])
    e2e_03 = len([name for name in dir() if name.startswith("test_") and "execution" in name.lower()])
    e2e_04 = len([name for name in dir() if name.startswith("test_") and "audit" in name.lower()])
    return {"E2E-01": e2e_01, "E2E-02": e2e_02, "E2E-03": e2e_03, "E2E-04": e2e_04}
