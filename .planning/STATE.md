# Chiffon: Project State

**Project:** Chiffon (Orchestrated AI Agents for Homelab Automation)
**Version:** 1.0 (v1 Roadmap Approved)
**Last Updated:** 2026-01-19 (02-05 Message Bus Integration complete)

---

## Project Reference

### Core Value (North Star)

**Autonomous delivery of infrastructure changes and features with full visibility, approval gates, and cost optimization.**

Everything else can fail. This must work:
1. Users can request infrastructure work in natural language
2. System executes it with auditability (git trail + DB logs)
3. Cost tracking prevents runaway external AI calls
4. Failures are logged for post-mortem analysis and workflow improvement

### Project Scope

**v1 Goals:**
- Prove orchestrator + infrastructure agent model
- Demonstrate full workflow via Kuma deployment use case
- Establish auditability and cost awareness patterns
- Foundation for v2 additions (post-mortem agent, code agent, planner, voice interface)

**v1 Constraints:**
- Single developer (you) + Claude
- Infrastructure: Existing Ansible + Docker tooling; agent integrates, not replaces
- Cost: Minimize external AI; use local Ollama/llama.cpp + Claude fallback
- Deployment: Docker across homelab (Unraid, Proxmox, Windows desktops)
- GPU availability variable; agents must be offline-tolerant

### Success Criteria (v1 Validation)

System is validated when:
1. User requests "Deploy Kuma Uptime to homelab and add existing portals to config"
2. Orchestrator parses intent, finds existing Kuma configs, presents plan
3. User approves; system executes via infra agent
4. Ansible playbooks run, output streamed, completion logged
5. Infra agent suggests playbook improvements
6. All changes committed to git with audit trail
7. State recorded in PostgreSQL (task, duration, resources, outcome)
8. User can review full audit trail from chat interface

---

## Current Position

### Phase Progress

**Roadmap Status:** ✓ Approved and ready for execution

| Phase | Status | Progress |
|-------|--------|----------|
| Phase 1: Foundation | ✓ Complete | 100% (5/5 plans) |
| Phase 2: Message Bus | ✓ Complete | 100% (5/5 plans) |
| Phase 3: Orchestrator Core | Pending | 0% |
| Phase 4: Desktop Agent | Pending | 0% |
| Phase 5: State & Audit | Pending | 0% |
| Phase 6: Infrastructure Agent | Pending | 0% |
| Phase 7: User Interface | Pending | 0% |
| Phase 8: E2E Integration | Pending | 0% |

**Overall Progress:** 14/40 plans complete (35%)

### Current Focus

**Currently executing:** Phase 3: Orchestrator Core (Pending)
**Last completed:** 02-05-integration-PLAN.md (63 end-to-end integration tests, all passing, message bus fully validated)
**Verification:** Message bus topology verified, RabbitMQ queues durable, priority routing working, DLX configured, all correlation IDs propagating correctly
**Next action:** Execute 03-PLAN files (Phase 3: Orchestrator Core - planning logic, work dependencies, multi-agent routing)

---

## Performance Metrics

### Requirement Coverage

- **Total v1 Requirements:** 28
- **Mapped to Phases:** 28 (100%)
- **Categories Covered:** 7/7 (Orchestrator, State, Message Bus, Desktop, Infra, UI, E2E)

### Phase Breakdown

| Phase | Requirements | Success Criteria |
|-------|--------------|------------------|
| 1 | 3 | 5 |
| 2 | 4 | 5 |
| 3 | 3 | 5 |
| 4 | 4 | 5 |
| 5 | 4 | 5 |
| 6 | 4 | 5 |
| 7 | 4 | 5 |
| 8 | 4 | 5 |

**Largest Phase:** Phase 2 (Message Bus), Phase 4-8 (4 req each)
**Smallest Phase:** Phase 1 (3 req core, 2 shared)

### Critical Dependencies

1. Phase 1 (Foundation) → prerequisite for all
2. Phase 2 (Message Bus) → prerequisite for Phases 3, 4, 6
3. Phase 3 (Orchestrator) → prerequisite for Phases 5, 7
4. Phase 4 (Desktop Agent) + Phase 5 (State) → prerequisite for Phase 6
5. Phase 6 (Infra Agent) + Phase 7 (UI) → prerequisite for Phase 8

---

## Accumulated Context

### Key Decisions

| Decision | Rationale | Status |
|----------|-----------|--------|
| Start with Orchestrator + Infra Agent only | Proof-of-concept: resource-aware dispatch + infrastructure integration. Avoids complexity of full planner/researcher/etc | Approved |
| Git + PostgreSQL state model | Git for immutable audit (commits), PostgreSQL for real-time state + queries. Enables post-mortems + auditability | Approved |
| RabbitMQ + FastAPI stack | Battle-tested async dispatch; Python ecosystem (GSD compatible). Simpler than gRPC, more robust than git-polling | Approved |
| Desktop agents report resource status | Real-time accuracy on GPU availability. Enables intelligent scheduling, avoids failed task dispatch | Approved |
| Wrap existing Ansible playbooks | Reuse infrastructure patterns already working; infra agent orchestrates, not rewrites | Approved |
| Chat interface for v1 approval | Manual gates initially build confidence. Auto-approval in later phases as workflows proven | Approved |

### Architectural Patterns Established

1. **Message-Driven Orchestration:**
   - Central orchestrator dispatches work via RabbitMQ
   - Agents autonomous, loosely coupled
   - Status updates flow back through MQ

2. **Auditability-First:**
   - Every decision: PostgreSQL record + git commit
   - No silent failures
   - Post-mortem scaffolding ready (v2: analysis agent)

3. **Cost Optimization:**
   - Local LLM for routine planning
   - External AI (Claude) only when: quota <20%, complex reasoning, high-value work
   - Quota tracking in PostgreSQL

4. **Resource Awareness:**
   - Desktop agents heartbeat resource metrics
   - Orchestrator queries capacity before dispatch
   - Work queued/paused based on availability

5. **Integration Over Replacement:**
   - Wrap existing Ansible playbooks
   - Leverage Portainer, git-as-source-of-truth
   - Orchestrator adds coordination, not replaces

### Known Unknowns

1. **Local LLM Performance:** Will Ollama/llama.cpp be fast enough for real-time plan generation? May need to fall back to Claude more than anticipated.
2. **Ansible Output Streaming:** How to efficiently stream ansible-playbook output through RabbitMQ without overwhelming the queue?
3. **Resource Metrics Accuracy:** Can we trust desktop agent self-reported metrics, or do we need external validation (GPU query via nvidia-smi)?
4. **Scale Beyond v1:** Single orchestrator works for v1. Multi-orchestrator or event-sourced state needed for v2.

### Todos (Pre-Phase 1)

- [ ] Confirm PostgreSQL schema design (task, audit_log tables)
- [ ] Design git audit commit format (JSON structure, commit message format)
- [ ] Create agent protocol specification (message format, error codes)
- [ ] Set up development environment (Python version, linter, test framework)
- [ ] Plan RabbitMQ topology (queues for orchestrator, per-agent, replies)

### Blockers

None currently. All systems go.

---

## Completed Plans

### Phase 1: Foundation

| Plan | Name | Status | Summary | Commits |
|------|------|--------|---------|---------|
| 01-01 | Project Structure & Setup | Complete | Poetry config, dev tools, project layout, Docker stack, CI/CD | c1b1c0e, 2309ba8 |
| 01-02 | PostgreSQL Schema & ORM | Complete | Database models, Alembic migrations, sample data | c1c9ea5, a2c5ae1, 330c4e5 |
| 01-03 | Agent Protocol & Message Formats | Complete | Pydantic models, exception hierarchy, OpenAPI spec, 40 contract tests | 4f87427, c370f9a, 1e2e265 |
| 01-04 | LiteLLM Service & Ollama Integration | Complete | LiteLLM config, Python client wrapper, SETUP.md docs | 68b93dc, 61ea4f1, a42cbbc |
| 01-05 | Documentation & Verification | Complete | ARCHITECTURE.md, test-foundation.sh, README updates | 524b160, b471cdc |

**Phase 1 Progress:** 5/5 plans complete (100%)

### Phase 2: Message Bus

| Plan | Name | Status | Summary | Commits |
|------|------|--------|---------|---------|
| 02-01 | RabbitMQ Queue Topology | Complete | Queue topology module, RabbitMQ service verified | f32a2ca |
| 02-02 | Message Protocol Completion | Complete | 6 message types, 43 tests, async-native (aio-pika), priority queuing | 063e406, 8a3cfe8, 603c821 |
| 02-03 | Agent Framework | Complete | BaseAgent, TestAgent, 32 integration tests, IdempotencyCache | 340b938, 5f59e7d, b182db5, 7595387 |
| 02-04 | Orchestrator REST API | Complete | 4 REST endpoints, OrchestratorService, 57 API tests, background tasks | 7b21bb9 |
| 02-05 | Message Bus Integration | Complete | 21 e2e test methods (63 cases), all passing, message bus fully validated | ecdce27, 4dfa7cc, dd2f17c |

**Phase 2 Progress:** 5/5 plans complete (100%)

---

## Session Continuity

### Last Session (2026-01-19 08:00 - 08:30)

**Completed:** 02-05-integration-PLAN.md (Message Bus Integration Testing)

**What was done:**
1. Created tests/test_e2e_message_bus.py (801 lines) with 21 test methods
2. Organized tests into 7 test classes covering all message bus scenarios
3. Implemented comprehensive test fixtures (rabbitmq_service, orchestrator_service, test_agent)
4. Fixed production bug: Added test work types to OrchestratorService mapping
5. Fixed production bug: Corrected DeliveryMode enum (NOT_PERSISTENT vs TRANSIENT)
6. All 63 test cases passing across 3 async backends (asyncio, trio, curio)

**What works now:**
- Complete message bus topology verified end-to-end
- RabbitMQ durable queues, priority routing, DLX routing all confirmed
- Agent framework connection management tested
- Orchestrator service dispatch/result handling tested
- Idempotency cache infrastructure validated
- Concurrent message processing verified
- Error scenarios and failure modes tested

**Test results:** 63/63 passing (21 methods × 3 backends), ~24 second execution

**Phase 2 Status:** COMPLETE - All 5 plans done
- Message bus fully operational and validated
- All 14 plans in Phase 1 + Phase 2 complete
- 35% of total roadmap complete (14/40 plans)

### Next Steps

1. Execute Phase 3 plans: Orchestrator Core
   - Planning logic and work orchestration
   - Multi-agent task routing
   - Distributed agent registry
2. Then Phase 4+: Desktop Agent, State & Audit, Infrastructure Agent, UI, E2E

### Context Pointers

- **Tech Stack:** Python + FastAPI, RabbitMQ, PostgreSQL, Docker
- **Homelab Integration:** Ansible playbooks in ~/CascadeProjects/homelab-infra, Git as source of truth
- **v1 Use Case:** Kuma Uptime deployment (discovery, planning, execution, audit)
- **Resource Constraints:** GPU desktops variable availability, external AI cost sensitive

---

**State Version:** 1.6
**Roadmap Locked:** 2026-01-18
**Last Execution:** 2026-01-19 - Completed 02-03-agent-framework-PLAN.md (BaseAgent, TestAgent, 32 integration tests, all passing)
**Next Execution:** Phase 2: Message Bus (02-04-orchestrator-rest-PLAN.md)
