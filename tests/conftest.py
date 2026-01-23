"""Pytest configuration and shared fixtures for end-to-end tests."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import aio_pika
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.agents.infra_agent.agent import InfraAgent
from src.agents.infra_agent.analyzer import PlaybookAnalyzer
from src.common.config import Config
from src.common.database import Base
from src.common.models import (
    AgentRegistry,
    DecomposedRequest,
    FallbackDecision,
    PlaybookCache,
    PlaybookSuggestion,
    Subtask,
    Task,
    WorkPlan,
    WorkTask,
)
from src.dashboard import api as dashboard_api
from src.dashboard.main import app as dashboard_app
from src.orchestrator.audit import AuditService
from src.orchestrator.service import OrchestratorService


class _AnsiblerunnerController:
    """Simple controller for mocking ansible_runner.run() results."""

    class RunnerStub:
        def __init__(
            self,
            rc: int = 0,
            events: list[dict] | None = None,
            stats: dict[str, dict] | None = None,
        ):
            self.rc = rc
            self.events = events or [
                {"event": "runner_on_ok", "event_data": {"task": "noop", "res": {"changed": False}}}
            ]
            self.stats = stats or {
                "localhost": {"ok": 1, "changed": 0, "failures": 0, "skipped": 0}
            }

    def __init__(self):
        self.call_history: list[dict[str, Any]] = []
        self._responses: list[_AnsiblerunnerController.RunnerStub] = []

    def queue_response(
        self, rc: int = 0, events: list[dict] | None = None, stats: dict[str, dict] | None = None
    ) -> None:
        """Push a canned runner result for the next invocation."""
        self._responses.append(self.RunnerStub(rc=rc, events=events, stats=stats))

    def run(self, **config: Any) -> RunnerStub:
        """Replacement for ansible_runner.run()."""
        self.call_history.append({"config": config})
        if self._responses:
            return self._responses.pop()
        return self.RunnerStub()


@pytest.fixture
async def async_client():
    """Provide an async HTTP client for testing the orchestrator FastAPI app."""

    from src.orchestrator.main import app as orchestrator_app

    async with AsyncClient(app=orchestrator_app, base_url="http://test") as client:
        yield client


@pytest.fixture
def test_database_url():
    """Provide a test database URL using in-memory SQLite."""

    yield "sqlite:///:memory:"


@pytest.fixture(scope="function")
def e2e_test_db():
    """Create a fresh in-memory SQLite database for each E2E test."""

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()

    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="infra",
        pool_name="infra_pool_e2e",
        capabilities={"run_playbook": True},
        status="online",
        resource_metrics={
            "cpu_cores_available": 8,
            "gpu_vram_available_gb": 4.0,
            "gpu_vram_total_gb": 8.0,
            "cpu_cores_physical": 8,
            "cpu_load_1min": 0.5,
            "cpu_load_5min": 0.3,
            "memory_available_gb": 12.0,
            "gpu_type": "none",
        },
        last_heartbeat_at=None,
    )
    session.add(agent)

    cache_entry = PlaybookCache(
        playbook_path="/tmp/kuma-deploy.yml",
        service_name="kuma",
        description="Deploy Kuma control plane (cached)",
        required_vars=["target_environment"],
        tags=["deploy", "kuma"],
        file_hash="deadbeef",
    )
    session.add(cache_entry)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(scope="function")
def temp_git_repo(tmp_path):
    """Create a temporary git repo with .audit/tasks for audit tests."""

    repo_dir = tmp_path / "e2e_git_repo"
    repo_dir.mkdir()
    subprocess.run(
        ["git", "init"],
        cwd=repo_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["git", "config", "user.email", "e2e@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Chiffon E2E"], cwd=repo_dir, check=True)
    audit_dir = repo_dir / ".audit" / "tasks"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "README.md").write_text("# Chiffon audit repo\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "chore: scaffold audit repo"], cwd=repo_dir, check=True)

    yield str(repo_dir)


@pytest.fixture(scope="function")
def mock_playbook_repo(tmp_path):
    """Create a temporary playbook repository with Kuma and portal playbooks."""

    repo_dir = tmp_path / "playbooks"
    repo_dir.mkdir()

    def _write(name: str, content: str) -> None:
        (repo_dir / name).write_text(content)

    _write(
        "kuma-deploy.yml",
        """# chiffon:service=kuma
# chiffon:description=Deploy Kuma control plane
- name: Deploy Kuma Control Plane
  hosts: all
  tags: [deploy, kuma]
  vars:
    target_environment: homelab
  tasks:
    - name: Ensure Kuma controller running
      ansible.builtin.debug:
        msg: "Installing Kuma"
""",
    )
    _write(
        "kuma-config-update.yml",
        """# chiffon:service=kuma
# chiffon:description=Update Kuma configuration
- name: Update Kuma config
  hosts: all
  tags: [config, kuma]
  vars:
    portals:
      - portal-1
      - portal-2
  tasks:
    - name: Push portal config
      ansible.builtin.debug:
        msg: "Sync portal configs"
""",
    )
    _write(
        "portal-1.yml",
        """# chiffon:service=portal
# chiffon:description=portal 1 lifecycle
- name: Manage portal-1
  hosts: all
  tags: [portal]
  tasks:
    - name: Ensure portal-1 deployed
      ansible.builtin.debug:
        msg: "Portal-1 alive"
""",
    )
    _write(
        "portal-2.yml",
        """# chiffon:service=portal
# chiffon:description=portal 2 lifecycle
- name: Manage portal-2
  hosts: all
  tags: [portal]
  tasks:
    - name: Ensure portal-2 deployed
      ansible.builtin.debug:
        msg: "Portal-2 alive"
""",
    )
    _write(
        "postgres-setup.yml",
        """# chiffon:service=postgres
# chiffon:description=Spin up Postgres cluster
- name: Setup Postgres
  hosts: all
  tags: [database]
  vars:
    pg_version: "15"
  tasks:
    - name: Ensure postgres package present
      ansible.builtin.debug:
        msg: "Postgres ready"
""",
    )

    yield str(repo_dir)


@pytest.fixture(scope="function")
def mock_ansible_runner(monkeypatch):
    """Provide a mock ansible_runner that does not touch disk."""

    controller = _AnsiblerunnerController()
    module_name = "ansible_runner"
    original_module = sys.modules.get(module_name)
    fake_module = SimpleNamespace(run=controller.run)
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    yield controller

    if original_module is not None:
        monkeypatch.setitem(sys.modules, module_name, original_module)
    else:
        sys.modules.pop(module_name, None)


@pytest.fixture(scope="function")
def mock_rabbitmq(monkeypatch):
    """Mock aio_pika connection/channel for messaging assertions."""

    class FakeExchange:
        def __init__(self):
            self.published: list[tuple[Any, str]] = []

        async def publish(self, message: Any, routing_key: str):
            self.published.append((message, routing_key))

    class FakeQueue:
        def __init__(self, name: str):
            self.name = name
            self.bindings: list[tuple[Any, str]] = []

        async def bind(self, exchange: Any, routing_key: str):
            self.bindings.append((exchange, routing_key))

    class FakeChannel:
        def __init__(self):
            self.default_exchange = FakeExchange()

        async def set_qos(self, prefetch_count: int):
            self.prefetch = prefetch_count

        async def declare_queue(self, name: str, **kwargs):
            return FakeQueue(name=name)

        async def declare_exchange(self, name: str, **kwargs):
            return FakeExchange()

    class FakeConnection:
        def __init__(self):
            self._channel = FakeChannel()
            self._closed = False

        async def channel(self):
            return self._channel

        async def close(self):
            self._closed = True

        @property
        def is_closed(self):
            return self._closed

    connection = FakeConnection()

    async def connect_robust(*args: Any, **kwargs: Any):
        return connection

    monkeypatch.setattr(aio_pika, "connect_robust", connect_robust)

    yield {
        "connection": connection,
        "channel": connection._channel,
        "published_messages": connection._channel.default_exchange.published,
    }


@pytest.fixture(scope="function")
def mock_litellm():
    """Mock LiteLLM client for fallback and analyzer interactions."""

    class MockLiteLLM:
        def __init__(self):
            self.usage_log: list[dict[str, Any]] = []

        def call_llm(
            self,
            model: str,
            messages: list[dict[str, str]],
            temperature: float = 0.7,
            max_tokens: int | None = None,
        ):
            record = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            self.usage_log.append(record)
            return {
                "choices": [{"message": {"content": f"{model} response"}}],
                "usage": {"total_tokens": 128},
            }

        def get_available_models(self):
            return ["claude-opus-4.5", "ollama/neural-chat"]

        def get_health(self):
            return True

    client = MockLiteLLM()
    return SimpleNamespace(client=client, usage_log=client.usage_log)


@pytest.fixture(scope="function")
def orchestrator_service_e2e(
    e2e_test_db: Session,
    mock_rabbitmq: dict[str, Any],
    mock_litellm: SimpleNamespace,
    temp_git_repo: str,
):
    """Initialize OrchestratorService wired for E2E verification."""

    config = Config()
    service = OrchestratorService(
        config, e2e_test_db, litellm_client=mock_litellm.client, repo_path=temp_git_repo
    )
    service.channel = mock_rabbitmq["channel"]
    service.connection = mock_rabbitmq["connection"]
    service.ws_manager = SimpleNamespace(broadcast=AsyncMock())

    decomposer = AsyncMock()

    async def _decompose(request_text: str):
        return DecomposedRequest(
            request_id=str(uuid4()),
            original_request=request_text,
            subtasks=[
                Subtask(
                    order=1,
                    name="Deploy Kuma",
                    intent="deploy_kuma",
                    confidence=0.95,
                    parameters={"service": "kuma"},
                ),
                Subtask(
                    order=2,
                    name="Update portals",
                    intent="update_portals",
                    confidence=0.88,
                    parameters={"portals": ["portal-1", "portal-2"]},
                ),
            ],
            ambiguities=[],
            out_of_scope=[],
            complexity_level="medium",
            decomposer_model="claude",
        )

    decomposer.decompose.side_effect = _decompose

    planner = AsyncMock()

    def _work_plan():
        return WorkPlan(
            plan_id=str(uuid4()),
            request_id="",
            tasks=[
                WorkTask(
                    order=1,
                    name="Deploy Kuma",
                    work_type="deploy_service",
                    agent_type="infra",
                    parameters={"service": "kuma"},
                    resource_requirements={
                        "estimated_duration_seconds": 120,
                        "gpu_vram_mb": 0,
                        "cpu_cores": 2,
                    },
                ),
                WorkTask(
                    order=2,
                    name="Update configuration",
                    work_type="run_playbook",
                    agent_type="infra",
                    parameters={"playbook_path": "kuma-config-update.yml"},
                    resource_requirements={
                        "estimated_duration_seconds": 60,
                        "gpu_vram_mb": 0,
                        "cpu_cores": 1,
                    },
                ),
            ],
            estimated_duration_seconds=180,
            complexity_level="medium",
            will_use_external_ai=False,
            status="pending_approval",
            human_readable_summary="Deploy Kuma Uptime to homelab and add our existing portals to the config",
        )

    async def _generate_plan(decomposed, available_resources):
        plan = _work_plan()
        return plan

    planner.generate_plan.side_effect = _generate_plan

    router = AsyncMock()

    async def _route(task):
        return SimpleNamespace(
            agent_id=str(uuid4()), agent_type="infra", score=0.9, selected_reason="best_fit"
        )

    router.route_task.side_effect = _route

    fallback = AsyncMock()

    async def _should_use(plan):
        decision = FallbackDecision(
            task_id=str(plan.plan_id),
            decision="use_ollama",
            reason="local_sufficient",
            quota_remaining_percent=0.5,
            complexity_level=plan.complexity_level,
            fallback_tier=1,
            model_used="ollama/neural-chat",
        )
        return decision, False

    fallback.should_use_external_ai.side_effect = _should_use

    service.initialize_components(
        decomposer=decomposer,
        planner=planner,
        router=router,
        fallback=fallback,
    )

    yield service


@pytest.fixture(scope="function")
def infra_agent_e2e(
    mock_playbook_repo: str,
    e2e_test_db: Session,
    mock_ansible_runner: _AnsiblerunnerController,
    monkeypatch: pytest.MonkeyPatch,
):
    """InfraAgent configured to use mocked runner and playbooks."""

    monkeypatch.setattr(
        PlaybookAnalyzer,
        "_run_ansible_lint",
        lambda self, path: [
            {
                "rule": {"id": "no-changed-when"},
                "message": "Use changed_when to prevent drifts.",
                "level": "error",
                "location": {"path": path, "lines": {"begin": 10}},
            }
        ],
    )

    config = Config()
    config.db_session = e2e_test_db
    agent = InfraAgent(agent_id="infra-e2e", config=config, repo_path=mock_playbook_repo)
    return agent


@pytest.fixture(scope="function")
def dashboard_client_e2e(
    orchestrator_service_e2e: OrchestratorService,
    temp_git_repo: str,
    e2e_test_db: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    """Return a Dashboard TestClient wired to the orchestrator service."""

    session_store = dashboard_api.session_store

    async def _fake_orchestrator_request(
        method: str, path: str, json: dict | None = None, params: dict | None = None
    ):
        payload = json or {}
        if method == "POST" and path == "/api/v1/request":
            return await orchestrator_service_e2e.submit_request(
                payload["request"], payload["user_id"]
            )

        if method == "GET" and path.startswith("/api/v1/plan/") and "/status" not in path:
            request_id = path.rsplit("/", 1)[-1]
            return await orchestrator_service_e2e.generate_plan(request_id)

        if method == "GET" and path.endswith("/status"):
            plan_id = path.split("/api/v1/plan/")[1].split("/status")[0]
            return await orchestrator_service_e2e.get_plan_status(plan_id)

        if method == "POST" and path.endswith("/approve"):
            plan_id = path.split("/api/v1/plan/")[1].split("/")[0]
            return await orchestrator_service_e2e.approve_plan(
                plan_id, payload.get("approved", True)
            )

        raise ValueError(f"Unsupported orchestrator path: {path}")

    monkeypatch.setattr(dashboard_api, "_orchestrator_request", _fake_orchestrator_request)
    session_store.clear()

    audit_service = AuditService(e2e_test_db)

    route_exists = any(
        route.path == "/api/dashboard/audit/task/{task_id}" for route in dashboard_app.routes
    )
    if not route_exists:

        @dashboard_app.get("/api/dashboard/audit/task/{task_id}")
        async def _audit_task(task_id: str):
            task_uuid = UUID(task_id)
            task = e2e_test_db.query(Task).filter(Task.task_id == task_uuid).first()
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            audit_path = Path(temp_git_repo) / ".audit" / "tasks" / f"{task_id}.json"
            audit_entry = json.loads(audit_path.read_text()) if audit_path.exists() else {}
            suggestions = (
                e2e_test_db.query(PlaybookSuggestion)
                .filter(PlaybookSuggestion.task_id == task_uuid)
                .all()
            )
            return {
                "task": {
                    "task_id": str(task.task_id),
                    "status": task.status,
                    "request_text": task.request_text,
                },
                "audit_entry": audit_entry,
                "suggestions": [
                    {
                        "id": s.id,
                        "category": s.category,
                        "rule_id": s.rule_id,
                        "severity": s.severity,
                        "status": s.status,
                    }
                    for s in suggestions
                ],
            }

    with TestClient(dashboard_app) as client:
        yield client
    session_store.clear()
