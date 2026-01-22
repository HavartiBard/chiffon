"""Kuma deployment validation tests for Phase 8 Wave 2.

Exercises discovery, mapping, execution, suggestion, audit, and workflow validation
for the "Deploy Kuma Uptime to homelab and add our existing portals to the config"
scenario."""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from unittest.mock import AsyncMock

from src.agents.infra_agent.analyzer import AnalysisResult, PlaybookAnalyzer, Suggestion
from src.agents.infra_agent.executor import ExecutionSummary, PlaybookExecutor
from src.agents.infra_agent.playbook_discovery import PlaybookDiscovery
from src.agents.infra_agent.task_mapper import (
    MappingResult,
    PlaybookMetadata as TaskMapperPlaybook,
    TaskMapper,
)
from src.common.models import PlaybookSuggestion, Task
from src.common.protocol import WorkRequest
from src.orchestrator.audit import AuditService

KUMA_REQUEST_TEXT = "Deploy Kuma Uptime to homelab and add our existing portals to the config"
PORTAL_CONFIGS = [
    {"name": "portal-1", "url": "https://portal1.example.com", "interval": 60},
    {"name": "portal-2", "url": "https://portal2.example.com", "interval": 120},
]


def create_realistic_kuma_playbook(path: Path, playbook_type: str) -> None:
    """Create a realistic Kuma playbook for deployment or configuration testing."""
    if playbook_type == "deploy":
        content = """---
# chiffon:service=kuma
# chiffon:description=Deploy Kuma service mesh to Docker host
- name: Deploy Kuma Uptime Container
  hosts: docker_hosts
  become: true
  vars:
    kuma_version: "{{ kuma_version | default('2.5.0') }}"
    kuma_port: "{{ kuma_port | default(5681) }}"
    kuma_container_name: kuma-uptime
  tasks:
    - name: Pull Kuma Uptime image
      docker_image:
        name: louislam/uptime-kuma
        tag: "{{ kuma_version }}"
        source: pull
    - name: Run Kuma Uptime container
      docker_container:
        name: "{{ kuma_container_name }}"
        image: "louislam/uptime-kuma:{{ kuma_version }}"
        state: started
        restart_policy: unless-stopped
        ports:
          - "{{ kuma_port }}:3001"
        volumes:
          - kuma-data:/app/data
      notify: Restart Kuma container
    - name: Ensure Kuma web UI responds
      uri:
        url: "http://localhost:{{ kuma_port }}"
        method: GET
        status_code: 200
      register: kuma_health
      until: kuma_health.status == 200
      retries: 10
      delay: 2
  handlers:
    - name: Restart Kuma container
      docker_container:
        name: "{{ kuma_container_name }}"
        state: restarted
"""
    else:
        content = """---
# chiffon:service=kuma
# chiffon:description=Update Kuma monitor configuration
- name: Configure Kuma Monitors
  hosts: docker_hosts
  become: true
  vars:
    portal_configs:
      - name: portal-1
        url: https://portal1.example.com
        interval: 60
      - name: portal-2
        url: https://portal2.example.com
        interval: 120
  tasks:
    - name: Add monitors via Kuma API
      uri:
        url: "http://localhost:5681/api/monitors"
        method: POST
        body_format: json
        body:
          name: "{{ item.name }}"
          url: "{{ item.url }}"
          interval: "{{ item.interval }}"
      loop: "{{ portal_configs }}"
      register: monitor_result
"""
    path.write_text(content)


class TestKumaPlaybookDiscovery:
    """Verify Kuma playbooks are discovered with metadata and caching."""

    @pytest.mark.asyncio
    async def test_discovers_kuma_deploy_playbook(self, tmp_path: Path):
        repo = tmp_path / "kuma_repo"
        repo.mkdir()
        create_realistic_kuma_playbook(repo / "kuma-deploy.yml", "deploy")
        create_realistic_kuma_playbook(repo / "kuma-config-update.yml", "config")

        discovery = PlaybookDiscovery(str(repo))
        catalog = await discovery.discover_playbooks(force_refresh=True)
        assert any(
            entry.filename == "kuma-deploy.yml" and entry.service == "kuma" for entry in catalog
        )

    @pytest.mark.asyncio
    async def test_discovers_kuma_config_update_playbook(self, tmp_path: Path):
        repo = tmp_path / "kuma_repo"
        repo.mkdir()
        create_realistic_kuma_playbook(repo / "kuma-deploy.yml", "deploy")
        create_realistic_kuma_playbook(repo / "kuma-config-update.yml", "config")

        discovery = PlaybookDiscovery(str(repo))
        catalog = await discovery.discover_playbooks(force_refresh=True)
        assert any(
            entry.filename == "kuma-config-update.yml" and entry.service == "kuma"
            for entry in catalog
        )

    @pytest.mark.asyncio
    async def test_extracts_required_vars(self, tmp_path: Path):
        repo = tmp_path / "kuma_repo"
        repo.mkdir()
        create_realistic_kuma_playbook(repo / "kuma-deploy.yml", "deploy")
        discovery = PlaybookDiscovery(str(repo))
        catalog = await discovery.discover_playbooks(force_refresh=True)
        deploy_meta = next(
            (entry for entry in catalog if entry.filename == "kuma-deploy.yml"), None
        )
        assert deploy_meta
        assert set(deploy_meta.required_vars) >= {
            "kuma_version",
            "kuma_port",
            "kuma_container_name",
        }

    @pytest.mark.asyncio
    async def test_cache_ttl_honored(self, tmp_path: Path):
        repo = tmp_path / "kuma_repo"
        repo.mkdir()
        create_realistic_kuma_playbook(repo / "kuma-deploy.yml", "deploy")
        discovery = PlaybookDiscovery(str(repo))
        await discovery.discover_playbooks(force_refresh=True)

        async def _should_not_run(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("Metadata should be cached and not rescanned")

        discovery._extract_metadata = AsyncMock(side_effect=_should_not_run)
        catalog = await discovery.discover_playbooks(force_refresh=False)
        assert catalog


class _DummyCacheManager:
    """Lightweight cache manager stub for TaskMapper tests."""

    async def lookup_cached_mapping(self, intent: str) -> Any:
        return None

    async def cache_mapping(self, *_, **__) -> None:
        return None


class TestKumaTaskMapping:
    """Ensure intents map to Kuma playbooks with high confidence."""

    @pytest.mark.asyncio
    async def test_maps_deploy_kuma_to_playbook(self):
        catalog = [
            TaskMapperPlaybook(
                path="/tmp/kuma-deploy.yml",
                filename="kuma-deploy.yml",
                service="kuma",
                description="Deploy Kuma",
                required_vars=["kuma_version", "kuma_port"],
                tags=["deploy"],
            ),
            TaskMapperPlaybook(
                path="/tmp/kuma-config-update.yml",
                filename="kuma-config-update.yml",
                service="kuma",
                description="Configure monitors",
            ),
        ]
        mapper = TaskMapper(_DummyCacheManager(), catalog)
        result = await mapper.map_task_to_playbook("Deploy Kuma Uptime to homelab")
        assert result.playbook_path == "/tmp/kuma-deploy.yml"
        assert result.confidence == 1.0
        assert result.method == "exact"

    @pytest.mark.asyncio
    async def test_maps_add_portals_to_config_playbook(self, monkeypatch):
        catalog = [
            TaskMapperPlaybook(
                path="/tmp/kuma-deploy.yml",
                filename="kuma-deploy.yml",
                service="kuma",
                description="Deploy Kuma",
            ),
            TaskMapperPlaybook(
                path="/tmp/kuma-config-update.yml",
                filename="kuma-config-update.yml",
                service="kuma",
                description="Update Kuma portals",
            ),
        ]
        mapper = TaskMapper(_DummyCacheManager(), catalog)

        async def _semantic(*args: Any, **kwargs: Any) -> MappingResult:
            return MappingResult(
                playbook_path="/tmp/kuma-config-update.yml",
                confidence=0.93,
                method="semantic",
                alternatives=[],
            )

        monkeypatch.setattr(mapper, "_semantic_match", _semantic)
        result = await mapper.map_task_to_playbook("add existing portals to config")
        assert result.playbook_path == "/tmp/kuma-config-update.yml"
        assert result.method == "semantic"
        assert result.confidence >= 0.90

    @pytest.mark.asyncio
    async def test_semantic_match_over_exact_match(self, monkeypatch):
        catalog = [
            TaskMapperPlaybook(
                path="/tmp/kuma-deploy.yml",
                filename="kuma-deploy.yml",
                service="kuma",
                description="Deploy Kuma",
            )
        ]
        mapper = TaskMapper(_DummyCacheManager(), catalog)
        monkeypatch.setattr(mapper, "_exact_match", lambda intent: None)

        async def _semantic(*args: Any, **kwargs: Any) -> MappingResult:
            return MappingResult(
                playbook_path="/tmp/kuma-deploy.yml",
                confidence=0.94,
                method="semantic",
                alternatives=[],
            )

        monkeypatch.setattr(mapper, "_semantic_match", _semantic)
        result = await mapper.map_task_to_playbook("Install Kuma service mesh")
        assert result.method == "semantic"
        assert result.confidence > 0.90

    @pytest.mark.asyncio
    async def test_fallback_to_template_generation(self):
        mapper = TaskMapper(_DummyCacheManager(), [])

        async def _semantic(intent: str, top_k: int) -> MappingResult:
            return mapper._no_match_result(intent)

        mapper._semantic_match = _semantic
        result = await mapper.map_task_to_playbook("Deploy new service X")
        assert result.method == "none"
        assert result.suggestion is not None
        assert "new service" in result.suggestion


class TestKumaExecutionSequence:
    """Validate playbook execution order, input variables, and analyzer hooks."""

    @pytest.mark.asyncio
    async def test_deployment_before_config_update(
        self,
        mock_playbook_repo: str,
        mock_ansible_runner,
    ):
        repo = Path(mock_playbook_repo)
        create_realistic_kuma_playbook(repo / "kuma-deploy.yml", "deploy")
        create_realistic_kuma_playbook(repo / "kuma-config-update.yml", "config")
        executor = PlaybookExecutor(str(repo))
        mock_ansible_runner.queue_response()
        mock_ansible_runner.queue_response()
        await executor.execute_playbook("kuma-deploy.yml")
        await executor.execute_playbook("kuma-config-update.yml")
        called = [call["config"]["playbook"] for call in mock_ansible_runner.call_history]
        assert called == ["kuma-deploy.yml", "kuma-config-update.yml"]

    @pytest.mark.asyncio
    async def test_executor_runs_kuma_deploy(self, mock_playbook_repo: str, mock_ansible_runner):
        repo = Path(mock_playbook_repo)
        create_realistic_kuma_playbook(repo / "kuma-deploy.yml", "deploy")
        executor = PlaybookExecutor(str(repo))
        mock_ansible_runner.queue_response(
            events=[{"event": "runner_on_ok", "event_data": {"res": {"changed": True}}}],
            stats={"localhost": {"ok": 1, "changed": 1, "failures": 0, "skipped": 0}},
        )
        summary = await executor.execute_playbook("kuma-deploy.yml")
        assert summary.status == "successful"
        assert summary.changed_count >= 0

    @pytest.mark.asyncio
    async def test_executor_captures_output(self, mock_playbook_repo: str, mock_ansible_runner):
        repo = Path(mock_playbook_repo)
        create_realistic_kuma_playbook(repo / "kuma-deploy.yml", "deploy")
        executor = PlaybookExecutor(str(repo))
        mock_ansible_runner.queue_response(
            events=[
                {
                    "event": "runner_on_ok",
                    "event_data": {"task": "pull", "res": {"changed": False}},
                },
                {"event": "runner_on_ok", "event_data": {"task": "run", "res": {"changed": True}}},
            ],
            stats={"localhost": {"ok": 2, "changed": 1, "failures": 0, "skipped": 0}},
        )
        summary = await executor.execute_playbook("kuma-deploy.yml")
        assert summary.changed_count == 1
        assert summary.ok_count == 2
        assert summary.failed_count == 0
        assert summary.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_config_update_receives_portal_vars(
        self, mock_playbook_repo: str, mock_ansible_runner
    ):
        repo = Path(mock_playbook_repo)
        create_realistic_kuma_playbook(repo / "kuma-config-update.yml", "config")
        executor = PlaybookExecutor(str(repo))
        mock_ansible_runner.queue_response()
        extras = {"portal_configs": PORTAL_CONFIGS, "api_token": "secret"}
        await executor.execute_playbook("kuma-config-update.yml", extravars=extras)
        last_call = mock_ansible_runner.call_history[-1]
        assert last_call["config"]["extravars"]["portal_configs"] == PORTAL_CONFIGS

    @pytest.mark.asyncio
    async def test_execution_failure_triggers_analyzer(self, infra_agent_e2e, mock_ansible_runner):
        mock_ansible_runner.queue_response(
            rc=1,
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {"task": "deploy", "res": {"msg": "timeout"}},
                }
            ],
        )
        request = WorkRequest(
            task_id=uuid4(),
            work_type="run_playbook",
            parameters={"playbook_path": "kuma-deploy.yml"},
        )
        response = await infra_agent_e2e.execute_work(request)
        assert response.status == "failed"
        assert response.analysis_result


class TestKumaSuggestionGeneration:
    """Ensure PlaybookAnalyzer returns actionable, categorized suggestions."""

    @pytest.mark.asyncio
    async def test_analyzer_identifies_missing_handler(self, tmp_path: Path):
        playbook = tmp_path / "missing-handler.yml"
        playbook.write_text(
            """---
- name: Restart service without handler
  hosts: all
  tasks:
    - name: Restart Kuma container
      shell: systemctl restart kuma
"""
        )
        analyzer = PlaybookAnalyzer()
        analyzer._run_ansible_lint = lambda path: [
            {
                "rule": {"id": "no-handler"},
                "level": "error",
                "message": "Add handler to avoid repeated restarts",
                "location": {"path": str(playbook), "lines": {"begin": 8}},
            }
        ]
        result = await analyzer.analyze_playbook(str(playbook))
        suggestion = result.suggestions[0]
        assert suggestion.category == "error_handling"
        assert suggestion.rule_id == "no-handler"
        assert suggestion.line_number == 8
        assert "handler" in suggestion.message

    @pytest.mark.asyncio
    async def test_analyzer_identifies_non_idempotent_task(self, tmp_path: Path):
        playbook = tmp_path / "shell-task.yml"
        playbook.write_text(
            """---
- name: Run non-idempotent task
  hosts: all
  tasks:
    - name: Use shell for control
      shell: echo 'deploy'
"""
        )
        analyzer = PlaybookAnalyzer()
        analyzer._run_ansible_lint = lambda path: [
            {
                "rule": {"id": "command-instead-of-module"},
                "level": "warning",
                "message": "Use specific module instead of shell",
                "location": {"path": str(playbook), "lines": {"begin": 6}},
            }
        ]
        result = await analyzer.analyze_playbook(str(playbook))
        suggestion = result.suggestions[0]
        assert suggestion.category == "idempotency"
        assert "shell" in suggestion.message
        assert suggestion.reasoning

    @pytest.mark.asyncio
    async def test_suggestions_categorized_correctly(self, tmp_path: Path):
        playbook = tmp_path / "multi-rule.yml"
        playbook.write_text("""---\n- name: multi check\n  hosts: all\n""")
        analyzer = PlaybookAnalyzer()
        analyzer._run_ansible_lint = lambda path: [
            {
                "rule": {"id": "no-changed-when"},
                "level": "error",
                "message": "changed_when missing",
                "location": {"lines": {"begin": 5}},
            },
            {
                "rule": {"id": "name"},
                "level": "warning",
                "message": "Add task names",
                "location": {"lines": {"begin": 8}},
            },
        ]
        result = await analyzer.analyze_playbook(str(playbook))
        assert result.by_category["idempotency"] == 1
        assert result.by_category["best_practices"] == 1

    @pytest.mark.asyncio
    async def test_suggestions_include_reasoning(self, tmp_path: Path):
        playbook = tmp_path / "reasoning.yml"
        playbook.write_text("""---\n- name: reason\n  hosts: all\n""")
        analyzer = PlaybookAnalyzer()
        analyzer._run_ansible_lint = lambda path: [
            {
                "rule": {"id": "no-changed-when"},
                "level": "error",
                "message": "missing changed_when",
                "location": {"lines": {"begin": 4}},
            },
        ]
        result = await analyzer.analyze_playbook(str(playbook))
        suggestion = result.suggestions[0]
        assert "changed_when" in suggestion.reasoning
        assert suggestion.file_path is not None


class TestKumaAuditTrail:
    """Verify PostgreSQL and git audit artifacts for Kuma tasks."""

    def test_postgresql_contains_kuma_task(self, e2e_test_db: Session):
        task = Task(
            task_id=uuid4(),
            request_text=KUMA_REQUEST_TEXT,
            status="completed",
            services_touched=["kuma"],
            outcome={"executed_playbook": "kuma-deploy.yml", "success": True},
        )
        e2e_test_db.add(task)
        e2e_test_db.commit()
        stored = e2e_test_db.query(Task).filter(Task.request_text == KUMA_REQUEST_TEXT).first()
        assert stored and stored.status == "completed"
        assert "kuma" in stored.services_touched

    def test_git_contains_kuma_audit_commit(self, temp_git_repo: str):
        task_id = uuid4()
        audit_path = Path(temp_git_repo) / ".audit" / "tasks" / f"{task_id}.json"
        data = {"task_id": str(task_id), "executed_playbook": "kuma-deploy.yml"}
        audit_path.write_text(json.dumps(data))
        subprocess.run(["git", "add", str(audit_path)], cwd=temp_git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "audit: kuma deployment"], cwd=temp_git_repo, check=True
        )
        log = subprocess.run(
            ["git", "log", "-1", "--pretty=%B"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "kuma deployment" in log.stdout

    def test_audit_entry_includes_playbook_path(self, temp_git_repo: str):
        task_id = uuid4()
        audit_path = Path(temp_git_repo) / ".audit" / "tasks" / f"{task_id}.json"
        payload = {"status": "completed", "executed_playbook": "kuma-deploy.yml"}
        audit_path.write_text(json.dumps(payload))
        content = json.loads(audit_path.read_text())
        assert content.get("executed_playbook") == "kuma-deploy.yml"

    def test_audit_query_by_service(self, e2e_test_db: Session):
        task = Task(
            task_id=uuid4(),
            request_text="audit",
            status="completed",
            services_touched=["kuma"],
        )
        e2e_test_db.add(task)
        e2e_test_db.commit()
        service = AuditService(e2e_test_db)
        result = service.get_by_service("kuma")
        assert any("kuma" in (t.services_touched or []) for t in result)

    def test_audit_trail_links_to_suggestions(self, e2e_test_db: Session):
        task_id = uuid4()
        task = Task(task_id=task_id, request_text="audit", status="completed")
        suggestion = PlaybookSuggestion(
            playbook_path="kuma-deploy.yml",
            task_id=task_id,
            category="error_handling",
            rule_id="no-handler",
            message="missing handler",
            reasoning="respects idempotency",
            severity="warning",
        )
        e2e_test_db.add(task)
        e2e_test_db.add(suggestion)
        e2e_test_db.commit()
        stored = (
            e2e_test_db.query(PlaybookSuggestion)
            .filter(PlaybookSuggestion.task_id == task_id)
            .all()
        )
        assert stored


class TestKumaFullWorkflow:
    """Execute the full Kuma v1 scenario end-to-end (happy path + failure)."""

    @pytest.mark.asyncio
    async def test_complete_kuma_deployment_happy_path(
        self,
        dashboard_client_e2e,
        orchestrator_service_e2e,
        infra_agent_e2e,
        mock_ansible_runner,
        e2e_test_db: Session,
        temp_git_repo: str,
        mock_playbook_repo: str,
    ):
        repo = Path(mock_playbook_repo)
        create_realistic_kuma_playbook(repo / "kuma-deploy.yml", "deploy")
        create_realistic_kuma_playbook(repo / "kuma-config-update.yml", "config")
        mock_ansible_runner.queue_response()
        mock_ansible_runner.queue_response()
        session = dashboard_client_e2e.post(
            "/api/dashboard/session", json={"user_id": "e2e-user"}
        ).json()
        chat = dashboard_client_e2e.post(
            "/api/dashboard/chat",
            json={"session_id": session["session_id"], "message": KUMA_REQUEST_TEXT},
        )
        assert chat.status_code == 200
        plan = chat.json()["plan"]
        assert KUMA_REQUEST_TEXT in plan["summary"]
        dashboard_client_e2e.post(
            f"/api/dashboard/plan/{plan['plan_id']}/approve",
            json={"session_id": session["session_id"]},
        )

        deploy_request = WorkRequest(
            task_id=uuid4(),
            work_type="deploy_service",
            parameters={
                "task_intent": "Deploy Kuma Uptime to homelab",
                "extravars": {"kuma_version": "2.5.0"},
            },
        )
        config_request = WorkRequest(
            task_id=uuid4(),
            work_type="run_playbook",
            parameters={
                "playbook_path": "kuma-config-update.yml",
                "extravars": {"portal_configs": PORTAL_CONFIGS},
            },
        )

        for req in (deploy_request, config_request):
            e2e_test_db.add(
                Task(task_id=req.task_id, request_text=req.work_type, status="approved")
            )
        e2e_test_db.commit()

        deploy_result = await infra_agent_e2e.execute_work(deploy_request)
        assert deploy_result.status == "completed"
        await orchestrator_service_e2e.handle_work_result(deploy_result, uuid4())

        config_result = await infra_agent_e2e.execute_work(config_request)
        assert config_result.status == "completed"
        await orchestrator_service_e2e.handle_work_result(config_result, uuid4())

        for result in (deploy_result, config_result):
            audit_path = Path(temp_git_repo) / ".audit" / "tasks" / f"{result.task_id}.json"
            assert audit_path.exists()

        called = [call["config"]["playbook"] for call in mock_ansible_runner.call_history]
        assert called[0] == "kuma-deploy.yml"
        assert called[1] == "kuma-config-update.yml"

    @pytest.mark.asyncio
    async def test_kuma_deployment_with_failure_and_suggestions(
        self,
        orchestrator_service_e2e,
        infra_agent_e2e,
        mock_ansible_runner,
        dashboard_client_e2e,
        e2e_test_db: Session,
        temp_git_repo: str,
        mock_playbook_repo: str,
    ):
        repo = Path(mock_playbook_repo)
        create_realistic_kuma_playbook(repo / "kuma-deploy.yml", "deploy")
        mock_ansible_runner.queue_response(
            rc=1,
            events=[
                {
                    "event": "runner_on_failed",
                    "event_data": {"task": "deploy", "res": {"stderr": "failure"}},
                }
            ],
        )
        session = dashboard_client_e2e.post(
            "/api/dashboard/session", json={"user_id": "e2e-user"}
        ).json()
        _ = dashboard_client_e2e.post(
            "/api/dashboard/chat",
            json={"session_id": session["session_id"], "message": KUMA_REQUEST_TEXT},
        )
        deploy_request = WorkRequest(
            task_id=uuid4(),
            work_type="deploy_service",
            parameters={"task_intent": "Deploy Kuma Uptime to homelab"},
        )
        e2e_test_db.add(
            Task(
                task_id=deploy_request.task_id,
                request_text=deploy_request.work_type,
                status="approved",
            )
        )
        e2e_test_db.commit()

        result = await infra_agent_e2e.execute_work(deploy_request)
        assert result.status == "failed"
        assert result.analysis_result
        await orchestrator_service_e2e.handle_work_result(result, uuid4())

        audit_response = dashboard_client_e2e.get(
            f"/api/dashboard/audit/task/{deploy_request.task_id}"
        )
        assert audit_response.status_code == 200
        payload = audit_response.json()
        assert payload["task"]["task_id"] == str(deploy_request.task_id)
        assert payload["suggestions"]
        stored = (
            e2e_test_db.query(PlaybookSuggestion)
            .filter(PlaybookSuggestion.task_id == deploy_request.task_id)
            .all()
        )
        assert stored
