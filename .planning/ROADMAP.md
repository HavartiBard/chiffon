# Chiffon Roadmap

## Overview

Chiffon is an agentic orchestration platform for autonomous infrastructure delivery across a homelab. This roadmap maps 28 v1 requirements across 8 phases, ordered by dependencies. Each phase delivers a complete, verifiable capability; success criteria are observable user behaviors, not implementation tasks.

**Depth:** Standard (8 phases)
**Coverage:** 28/28 requirements mapped
**Target:** Prove orchestrator + infrastructure agent model via Kuma deployment v1 success criteria

---

## Phase Summary

| Phase | Goal | Requirements | Plans | Success Criteria |
|-------|------|--------------|-------|------------------|
| 1 - Foundation | Project infrastructure, observability stack ready | STATE-01, STATE-02, MSG-04 | 5 | 5 |
| 2 - Message Bus | RabbitMQ and agent communication protocol deployed | MSG-01, MSG-02, MSG-03, MSG-04 | 5/5 ✓ | 5/5 ✓ |
| 3 - Orchestrator Core | Orchestrator accepts requests, plans work, dispatches to agents | ORCH-01, ORCH-02, ORCH-05 | 5/5 ✓ | 5/5 ✓ |
| 4 - Desktop Agent | Agents report resource availability in real-time | DESK-01, DESK-02, DESK-03, DESK-04 | 5/5 ✓ | 5/5 ✓ |
| 5 - State & Audit | Execution tracked in PostgreSQL, audit trail committed to git | STATE-03, STATE-04, ORCH-03, ORCH-04 | 5/5 ✓ | 5/5 ✓ |
| 6 - Infrastructure Agent | Ansible integration, playbook execution, improvement suggestions | INFRA-01, INFRA-02, INFRA-03, INFRA-04 | 6 plans | 5 |
| 7 - User Interface | Chat interface, plan approval, execution transparency | UI-01, UI-02, UI-03, UI-04 | 6/6 ✓ | 5/5 ✓ |
| 8 - End-to-End Integration | Full Kuma deployment workflow with user → orchestrator → infra agent → git | E2E-01, E2E-02, E2E-03, E2E-04 | 2 plans | 5 |

---

## Phase Details

### Phase 1: Foundation & Observability Infrastructure

**Goal:** Project scaffolding, Docker environment, PostgreSQL schema, agent protocol specification. Foundation for all subsequent phases.

**Status:** ✓ COMPLETE (5/5 plans executed, goal verified)

**Plans:**
- [x] 01-01-PLAN.md — Project structure, Poetry, Docker setup
- [x] 01-02-PLAN.md — PostgreSQL schema, ORM models, Alembic migrations
- [x] 01-03-PLAN.md — Agent protocol spec, OpenAPI, contract tests
- [x] 01-04-PLAN.md — LiteLLM service setup, local Ollama, Python client
- [x] 01-05-PLAN.md — Documentation (SETUP.md, ARCHITECTURE.md), verification script

**Dependencies:** None (greenfield start)

**Requirements Mapped:**
- STATE-01: All decisions and execution results committed to git (immutable audit trail)
- STATE-02: PostgreSQL schema tracks task status, outcomes, resources used, timestamps
- MSG-04: Agent protocol defined and documented (message format, error handling, timeouts)

**Success Criteria:**

1. **PostgreSQL deployed and schema initialized** — User can connect to PostgreSQL, run sample queries against task status table, see schema includes fields for task_id, status, outcome, resource_usage, created_at, updated_at
2. **Git repository initialized with audit commit structure** — Initial commit exists, audit log directory structure ready, sample audit entry committed with proper formatting
3. **Agent protocol documented** — Protocol specification document exists with message format (JSON), required fields, error codes, timeout behavior
4. **Docker environment verified** — Docker compose file successfully starts PostgreSQL + RabbitMQ + Ollama + LiteLLM, all services healthy
5. **Project structure established** — Source code directories (src/orchestrator/, src/agents/, src/common/), configuration files, tests/, migrations/, docs/, logging setup functional

**Risks & Notes:**
- PostgreSQL schema must support future audit queries (filter by timestamp, service, status)
- Git audit trail structure designed for immutability (append-only logs)
- Agent protocol drives all downstream communication; versioning required

---

### Phase 2: Message Bus & Agent Communication

**Goal:** RabbitMQ deployed, agent communication protocol implemented and tested. Agents can exchange messages with orchestrator.

**Status:** ✓ COMPLETE (5/5 plans executed, goal verified)

**Plans:**
- [x] 02-01-PLAN.md — RabbitMQ deployment, queue topology, management UI verification
- [x] 02-02-PLAN.md — Protocol completion (all message types), comprehensive tests (40+ tests)
- [x] 02-03-PLAN.md — Agent framework base class, heartbeat loop, test agent
- [x] 02-04-PLAN.md — Orchestrator REST API (/dispatch, /status, /agents, /cancel)
- [x] 02-05-PLAN.md — End-to-end integration tests, error scenarios, persistence validation

**Dependencies:** Phase 1 (foundation established)

**Requirements Mapped:**
- MSG-01: RabbitMQ-based message queue for agent dispatch
- MSG-02: Agents receive work via MQ, send status updates back
- MSG-03: REST API for orchestrator queries and manual operations
- MSG-04: Agent protocol defined and documented (message format, error handling, timeouts)

**Success Criteria:**

1. **RabbitMQ deployed and accessible** — RabbitMQ service running, admin panel accessible, test queue creation/deletion works, docker compose integration verified
2. **Agent protocol messages round-trip** — Send sample work message from orchestrator, receive acknowledgment from agent, status updates returned; messages logged and auditable
3. **REST API operational** — FastAPI orchestrator service accepts /dispatch, /status, /resources endpoints; returns valid JSON responses; Swagger docs generated
4. **Error handling in protocol** — Send malformed message, receive error with code + description; timeout behavior tested (agent offline scenario); reconnection logic verified
5. **Agent framework ready** — Agent base class can connect to RabbitMQ, receive work, send status; test agent implementation included in codebase

**Risks & Notes:**
- RabbitMQ must survive orchestrator restarts (durable queues)
- Protocol versioning essential (v1.0 in schema)
- REST API becomes public interface for manual operations

---

### Phase 3: Orchestrator Core

**Goal:** Orchestrator service accepts natural language requests, structures them into work plans, routes to agents based on resource availability and capability. Can fall back to external AI when needed.

**Status:** ✓ COMPLETE (7/7 plans executed, goal verified)

**Plans:**
- [x] 03-01-PLAN.md — Request Parser & Intent Decomposer (NLU, auto-decompose requests into subtasks)
- [x] 03-02-PLAN.md — Work Plan Generation & Validation (sequential task lists, resource requirements, reordering)
- [x] 03-03-PLAN.md — Agent Routing & Registry (pool-based assignment, performance tracking, scoring)
- [x] 03-04-PLAN.md — External AI Fallback Integration (quota checks, complexity assessment, Claude fallback)
- [x] 03-05-PLAN.md — Orchestrator Service Integration & E2E Tests (REST API, approval workflow, full workflow tests)
- [x] 03-06-PLAN.md — Integration Completion (Gap closure: Full orchestrator integration)
- [x] 03-07-PLAN.md — Quota Validation Field Fix (Gap closure: Fix FallbackDecision quota field)

**Dependencies:** Phase 1 (state layer), Phase 2 (message bus)

**Requirements Mapped:**
- ORCH-01: Orchestrator accepts natural language requests and structures them into work plans
- ORCH-02: Orchestrator dispatches work to appropriate agent (infra, code, research, etc.) via message queue
- ORCH-05: Orchestrator falls back to external AI (Claude) when: local quota <20%, task requires complex reasoning, or work marked high-value

**Success Criteria:**

1. **Natural language to work plan** — User submits request "Deploy Kuma to homelab", orchestrator parses intent, returns structured plan (steps, estimated duration, resource requirements, approval needed)
2. **Agent routing logic works** — Orchestrator receives deployment request, routes to infra agent (not desktop or other); receives work dispatch via MQ; logs dispatch in PostgreSQL
3. **External AI fallback active** — Request marked as complex, orchestrator checks local quota, if <20% calls Claude API with context, returns enhanced plan; fallback decision logged
4. **Resource-aware dispatch** — Orchestrator queries desktop agents for available GPU VRAM before dispatching GPU-heavy work; skips offline agents; respects capacity constraints
5. **Work plan includes dependencies** — Complex request decomposed into sub-tasks with ordering (e.g., "check playbooks" before "execute deployment"); plan is human-readable

**Risks & Notes:**
- Natural language parsing must be robust (use local LLM or Claude with fallback)
- Agent type taxonomy must be extensible (v1: infra; v2: code, research, post-mortem)
- Quota management for external AI critical for cost control

---

### Phase 4: Desktop Agent (Resource Awareness)

**Goal:** Lightweight agents run on GPU desktops, report resource availability (CPU, GPU VRAM, load %), signal online/offline status. Orchestrator can query before dispatching work.

**Status:** ✓ COMPLETE (5/5 plans executed, goal verified)

**Dependencies:** Phase 2 (message bus)

**Requirements Mapped:**
- DESK-01: Lightweight agent runs on each GPU desktop, reports load percentage
- DESK-02: Desktop agent reports available GPU VRAM, CPU cores
- DESK-03: Desktop agent signals online/offline status to orchestrator
- DESK-04: Orchestrator can query desktop agent for work capacity before dispatch

**Success Criteria:**

1. **Agent installed and running on desktop** — Desktop agent process running, connects to RabbitMQ, registers in orchestrator's agent registry; service can be stopped/started without errors
2. **Resource metrics reported** — Agent sends heartbeat every 30s with CPU load (%), available GPU VRAM (GB), available CPU cores (#); metrics updated in real-time, queryable via orchestrator
3. **Online/offline status visible** — Agent goes offline (kill process), orchestrator detects within 60s; agent comes back online, orchestrator registers it; status queryable in real-time
4. **Capacity check works** — Orchestrator calls "get_available_capacity(agent_id)", receives GPU VRAM available, CPU cores available; can make routing decision based on response
5. **Multiple agents tracked** — 3 desktop agents running, orchestrator sees all 3 with distinct resources; can list agents, filter by available capacity

**Risks & Notes:**
- Agent must be lightweight (minimal resource footprint during idle)
- Heartbeat timeout must account for network jitter; recommend 90s threshold before offline
- Resource metrics must be accurate (no exaggeration of available capacity)

---

### Phase 5: State & Audit Integration

**Goal:** Execution results tracked in PostgreSQL with rich audit data. All decisions and outcomes committed to git as immutable audit trail. Audit queries support filtering by time, service, status.

**Status:** ✓ COMPLETE (5/5 plans executed + 2 gap closures, goal verified)

**Dependencies:** Phase 1 (PostgreSQL schema), Phase 3 (orchestrator), Phase 4 (desktop agent)

**Requirements Mapped:**
- STATE-03: Audit logs support querying: "all failures in last week", "all changes to service X"
- STATE-04: Scaffolding exists for future post-mortem agent (structured failure logs, optimization suggestions)
- ORCH-03: Orchestrator tracks execution state in PostgreSQL with audit trail commits to git
- ORCH-04: Orchestrator pauses/resumes execution based on available GPU resources on desktop agents

**Success Criteria:**

1. **Execution state persisted** — After work completes, orchestrator writes task record to PostgreSQL with id, status (success/failed), outcome (output/error), resources_used (GPU VRAM, CPU time), timestamps (start, end)
2. **Git audit trail immutable** — After task completes, orchestrator commits audit entry to git with format: task_id, plan, dispatch details, result, timestamp; git log shows chronological audit trail
3. **Audit queries work** — Query "SELECT * FROM tasks WHERE status = 'failed' AND created_at > '2026-01-11'" returns all failed tasks in last week; query "SELECT * FROM tasks WHERE service_touched = 'kuma'" returns all Kuma-related changes
4. **Pause/resume on resource constraints** — Orchestrator queues work for Kuma deployment, checks desktop agents, sees all at <10% capacity, pauses; when capacity available, resumes; pause/resume events logged in PostgreSQL and git
5. **Post-mortem scaffolding ready** — Failure records include error message, resource state at failure time, suggestions field (populated by v2 post-mortem agent); schema supports annotation

**Risks & Notes:**
- Git commit discipline critical; every task completion must commit (no silent failures)
- PostgreSQL queries must support complex filters (timestamp range, service name, status) without N+1 queries
- Pause/resume state must survive orchestrator restart

---

### Phase 6: Infrastructure Agent (Ansible Integration)

**Goal:** Agent accepts deployment tasks, maps to existing Ansible playbooks in ~/CascadeProjects/homelab-infra, executes playbooks, returns structured summaries, suggests improvements.

**Status:** PLANNED (6 plans in 3 waves)

**Plans:**
- [ ] 06-01-PLAN.md — Infrastructure Agent Foundation (InfraAgent class, PlaybookDiscovery service)
- [ ] 06-02-PLAN.md — Task-to-Playbook Mapping (TaskMapper with FAISS semantic matching)
- [ ] 06-03-PLAN.md — Playbook Execution & Output (PlaybookExecutor with ansible-runner)
- [ ] 06-04-PLAN.md — Improvement Suggestions (PlaybookAnalyzer with ansible-lint)
- [ ] 06-05-PLAN.md — Template Generation (TemplateGenerator with Jinja2 + Galaxy patterns)
- [ ] 06-06-PLAN.md — E2E Integration & Tests (Full workflow tests, orchestrator integration)

**Wave Structure:**
- Wave 1: Plans 01, 02 (independent foundation — can run in parallel)
- Wave 2: Plans 03, 04, 05 (depend on Wave 1 — can run in parallel)
- Wave 3: Plan 06 (depends on all prior — integration testing)

**Dependencies:** Phase 2 (message bus), Phase 3 (orchestrator)

**Requirements Mapped:**
- INFRA-01: Infra agent accepts deployment tasks and maps them to existing Ansible playbooks
- INFRA-02: Infra agent executes playbooks and streams output back to orchestrator
- INFRA-03: Infra agent suggests improvements to playbooks (new patterns, automation opportunities)
- INFRA-04: Infra agent generates new playbook templates for common tasks (service deployment, config updates)

**Success Criteria:**

1. **Playbook discovery works** — Agent scans ~/CascadeProjects/homelab-infra/ansible for playbooks, indexes by service name (kuma, portainer, etc.), caches with refresh every 1h; orchestrator can query playbook catalog
2. **Task → playbook mapping** — Orchestrator sends task "Deploy Kuma Uptime", agent parses intent, identifies kuma-deployment.yml playbook, verifies playbook exists; if no match, suggests closest match or "custom playbook needed"
3. **Execution and output summary** — Agent runs ansible-playbook with task, returns structured summary (status, duration, changed count, errors); exit code captured
4. **Improvement suggestions generated** — After playbook execution failure, agent analyzes for patterns: "Config not idempotent", "Missing handler for service restart", suggests improvement with reasoning; suggestions stored, can be applied to playbook
5. **Playbook templates generated** — Agent receives "Generate template for deploying [service]", produces YAML playbook scaffold with roles, handlers, variables, comments; user can copy to homelab-infra and customize

**Risks & Notes:**
- Playbook inventory must be accurate and up-to-date
- Ansible execution must use orchestrator context (user, privileges, vault access)
- Silent execution with high-level summaries preferred over line-by-line streaming (reduces MQ overhead)

---

### Phase 7: User Interface & Approval

**Goal:** Chat interface accepts natural language deployment requests. Orchestrator presents plan for approval. User can approve, reject, or request modifications before execution.

**Status:** ✓ COMPLETE (6/6 plans executed, goal verified)

**Plans:**
- [x] 07-01-PLAN.md — Dashboard Backend API (FastAPI, session management, orchestrator proxy)
- [x] 07-02-PLAN.md — WebSocket Real-time Layer (connection manager, execution streaming)
- [x] 07-03-PLAN.md — Chat Interface Frontend (React, TypeScript, Vite, TailwindCSS)
- [x] 07-04-PLAN.md — Plan Review & Approval UI (plan display, approve/reject/modify)
- [x] 07-05-PLAN.md — Execution Monitoring UI (real-time updates, abort, summary)
- [x] 07-06-PLAN.md — E2E Integration Tests (full workflow, requirement verification)

**Wave Structure:**
- Wave 1: Plans 01, 02 (independent backend foundation — can run in parallel)
- Wave 2: Plans 03, 04 (frontend components — depend on Wave 1)
- Wave 3: Plans 05, 06 (integration and testing — depend on Waves 1 and 2)

**Dependencies:** Phase 3 (orchestrator), Phase 6 (infra agent)

**Requirements Mapped:**
- UI-01: Chat interface accepts deployment requests in natural language
- UI-02: Orchestrator presents execution plan to user for approval
- UI-03: User can approve, reject, or request modifications to plan before execution
- UI-04: Execution log shows all steps, outputs, and decisions for transparency

**Success Criteria:**

1. **Chat interface operational** — Web or CLI interface available, user can type deployment request, request received by orchestrator; interface shows request status (pending, approved, executing, completed)
2. **Plan presentation format** — Orchestrator returns plan as: step-by-step execution list, estimated duration, resource requirements, risk level (low/medium/high); user can read plan in <1 minute
3. **Approval workflow works** — User clicks "Approve", orchestrator receives approval, begins execution; user clicks "Reject", orchestrator cancels; user clicks "Modify", can request changes (e.g., "use staging Kuma first")
4. **Real-time execution log** — During execution, each step displays with status (running, done, error); output from agents (ansible output, error messages) visible in real-time; user can abort mid-execution
5. **Post-execution summary** — After task completes, interface shows: all steps with results, total duration, resources used, link to git audit trail; user can review and share audit

**Risks & Notes:**
- UI must handle long-running operations (WebSocket or polling)
- Plan presentation must be jargon-free (translate to non-technical user language)
- Rejection/modification must not lose planning context (re-plan is acceptable, full restart not)

---

### Phase 8: End-to-End Integration (Kuma Deployment)

**Goal:** Complete workflow: user requests Kuma deployment, system finds existing configs, presents plan, executes via infra agent, suggests improvements, commits to git, tracks state. All components integrated and working.

**Status:** PLANNED (2 plans in 2 waves)

**Plans:**
- [ ] 08-01-PLAN.md — Full E2E Integration Tests (comprehensive test suite covering all integration points)
- [ ] 08-02-PLAN.md — Kuma Deployment Validation (real-world scenario validation with v1 validation report)

**Wave Structure:**
- Wave 1: Plan 01 (E2E integration test suite — autonomous)
- Wave 2: Plan 02 (Kuma deployment validation with human verification checkpoint — sequential)

**Dependencies:** All prior phases (1-7)

**Requirements Mapped:**
- E2E-01: Full workflow: user requests "Deploy Kuma Uptime, add existing portals to config"
- E2E-02: System finds existing Kuma configs/playbooks in ~/CascadeProjects/homelab-infra
- E2E-03: Infra agent deploys container, configures service, suggests playbook updates
- E2E-04: Updates committed to git, state recorded in DB, user reviews audit trail

**Success Criteria:**

1. **Full user request flow** — User submits "Deploy Kuma Uptime to homelab and add our existing portals to the config", orchestrator parses intent, identifies deployment + config update tasks, presents multi-step plan for approval
2. **Config discovery** — System finds existing Kuma playbooks and docker-compose stacks in ~/CascadeProjects/homelab-infra, identifies existing portal configurations, suggests which to include in updated Kuma config
3. **Deployment execution** — User approves plan, infra agent executes playbooks in sequence: kuma-deployment.yml, then kuma-config-update.yml, streams output to user, logs all steps in PostgreSQL
4. **Playbook suggestions applied** — After execution, infra agent suggests improvements to kuma-deployment.yml (e.g., "Add health check to service"), user can accept suggestion, improvement committed to playbooks
5. **Audit trail complete** — Git repo contains new commit with task details, execution log, all changes to Kuma configs; PostgreSQL records task state, outcome, resources used; user can review full audit trail from UI

**Risks & Notes:**
- This phase validates entire system; if any component fails, E2E fails
- Kuma deployment is archetypal; workflow must generalize to other services (Portainer, DNS, etc.) in future phases
- Success = user confidence that orchestrator is reliable, auditable, controllable

---

## Traceability

### Coverage Summary

**Total v1 Requirements:** 28
**Mapped Requirements:** 28
**Coverage:** 100% ✓

### Requirement → Phase Mapping

| Requirement | Phase | Status |
|-------------|-------|--------|
| STATE-01 | Phase 1, 5 | Phase 1: Complete, Phase 5: Complete |
| STATE-02 | Phase 1 | Complete |
| STATE-03 | Phase 5 | Complete |
| STATE-04 | Phase 5 | Complete |
| MSG-01 | Phase 2 | Complete |
| MSG-02 | Phase 2 | Complete |
| MSG-03 | Phase 2 | Complete |
| MSG-04 | Phase 1, 2 | Complete |
| ORCH-01 | Phase 3 | Complete |
| ORCH-02 | Phase 3 | Complete |
| ORCH-03 | Phase 5 | Complete |
| ORCH-04 | Phase 5 | Complete |
| ORCH-05 | Phase 3 | Complete |
| DESK-01 | Phase 4 | Complete |
| DESK-02 | Phase 4 | Complete |
| DESK-03 | Phase 4 | Complete |
| DESK-04 | Phase 4 | Complete |
| INFRA-01 | Phase 6 | Planned |
| INFRA-02 | Phase 6 | Planned |
| INFRA-03 | Phase 6 | Planned |
| INFRA-04 | Phase 6 | Planned |
| UI-01 | Phase 7 | Complete |
| UI-02 | Phase 7 | Complete |
| UI-03 | Phase 7 | Complete |
| UI-04 | Phase 7 | Complete |
| E2E-01 | Phase 8 | Planned |
| E2E-02 | Phase 8 | Planned |
| E2E-03 | Phase 8 | Planned |
| E2E-04 | Phase 8 | Planned |

---

## Execution Notes

### Phase Dependencies Graph

```
Phase 1 (Foundation)
  ↓
Phase 2 (Message Bus) ← Required by all agents
  ↙          ↘
Phase 3        Phase 4
(Orchestrator) (Desktop Agent)
  ↓              ↓
Phase 5 (State & Audit) ← Integrates state tracking + resource awareness
  ↓
Phase 6 (Infrastructure Agent)
  ↓
Phase 7 (User Interface)
  ↓
Phase 8 (End-to-End Integration)
```

### Critical Path

The critical path to v1 validation is: Phase 1 → Phase 2 → Phase 3 → Phase 5 → Phase 6 → Phase 7 → Phase 8.

Phases 4 (Desktop Agent) can run in parallel with Phases 3 after Phase 2 completes, but Phase 5 requires both.

### Success Metrics

Each phase has observable completion criteria. Phase 8 success means:
- User can request work in natural language
- System plans autonomously
- All execution auditable and reversible
- Cost tracking operational
- Resource awareness working

---

**Roadmap Version:** 1.5
**Created:** 2026-01-18
**Last Updated:** 2026-01-22 (Phase 8 planned: 2 plans in 2 waves)
**Current Status:** 36/48 plans complete (75%) — Phase 6 in progress, Phase 7 complete, Phase 8 planned
