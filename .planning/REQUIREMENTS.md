# Requirements: Chiffon

**Defined:** 2026-01-18
**Core Value:** Autonomous delivery of infrastructure changes and features with full visibility, approval gates, and cost optimization.

## v1 Requirements

Requirements for initial release. The Kuma deployment use case drives scope and validation.

### Orchestrator Core

- [ ] **ORCH-01**: Orchestrator accepts natural language requests and structures them into work plans
- [ ] **ORCH-02**: Orchestrator dispatches work to appropriate agent (infra, code, research, etc.) via message queue
- [ ] **ORCH-03**: Orchestrator tracks execution state in PostgreSQL with audit trail commits to git
- [ ] **ORCH-04**: Orchestrator pauses/resumes execution based on available GPU resources on desktop agents
- [ ] **ORCH-05**: Orchestrator falls back to external AI (Claude) when: local quota <20%, task requires complex reasoning, or work marked high-value

### State & Audit

- [ ] **STATE-01**: All decisions and execution results committed to git (immutable audit trail)
- [ ] **STATE-02**: PostgreSQL schema tracks task status, outcomes, resources used, timestamps
- [ ] **STATE-03**: Audit logs support querying: "all failures in last week", "all changes to service X"
- [ ] **STATE-04**: Scaffolding exists for future post-mortem agent (structured failure logs, optimization suggestions)

### Message Bus & Communication

- [ ] **MSG-01**: RabbitMQ-based message queue for agent dispatch
- [ ] **MSG-02**: Agents receive work via MQ, send status updates back
- [ ] **MSG-03**: REST API for orchestrator queries and manual operations
- [ ] **MSG-04**: Agent protocol defined and documented (message format, error handling, timeouts)

### Desktop Agent (Resource Awareness)

- [ ] **DESK-01**: Lightweight agent runs on each GPU desktop, reports load percentage
- [ ] **DESK-02**: Desktop agent reports available GPU VRAM, CPU cores
- [ ] **DESK-03**: Desktop agent signals online/offline status to orchestrator
- [ ] **DESK-04**: Orchestrator can query desktop agent for work capacity before dispatch

### Infrastructure Agent (Ansible Integration)

- [ ] **INFRA-01**: Infra agent accepts deployment tasks and maps them to existing Ansible playbooks
- [ ] **INFRA-02**: Infra agent executes playbooks and streams output back to orchestrator
- [ ] **INFRA-03**: Infra agent suggests improvements to playbooks (new patterns, automation opportunities)
- [ ] **INFRA-04**: Infra agent generates new playbook templates for common tasks (service deployment, config updates)

### User Interface & Approval

- [ ] **UI-01**: Chat interface accepts deployment requests in natural language
- [ ] **UI-02**: Orchestrator presents execution plan to user for approval
- [ ] **UI-03**: User can approve, reject, or request modifications to plan before execution
- [ ] **UI-04**: Execution log shows all steps, outputs, and decisions for transparency

### Integration & End-to-End

- [ ] **E2E-01**: Full workflow: user requests "Deploy Kuma Uptime, add existing portals to config"
- [ ] **E2E-02**: System finds existing Kuma configs/playbooks in ~/CascadeProjects/homelab-infra
- [ ] **E2E-03**: Infra agent deploys container, configures service, suggests playbook updates
- [ ] **E2E-04**: Updates committed to git, state recorded in DB, user reviews audit trail

## v2 Requirements

Deferred to future release. Build on proven v1 orchestrator + infra agent patterns.

### Post-Mortem & Optimization Agent

- **POST-01**: Agent analyzes failed tasks to identify root causes and suggest prevention
- **POST-02**: Agent identifies patterns (daily tasks, repeated fixes) and suggests optimizations
- **POST-03**: Post-mortem reports include: failure timeline, contributing factors, recommended improvements
- **POST-04**: Optimization suggestions tracked and marked "implemented" when applied

### Code Generation & Testing Agent

- **CODE-01**: Agent accepts code generation requests (new services, tools, utilities)
- **CODE-02**: Agent writes code, generates tests, suggests deployment strategy
- **CODE-03**: Agent executes tests in sandboxed environment
- **CODE-04**: Agent commits code and suggests infrastructure requirements

### Planner Agent (GSD-like)

- **PLAN-01**: Planner accepts project ideas and structures them (scope, research, roadmap)
- **PLAN-02**: Planner gathers requirements through interactive questioning
- **PLAN-03**: Planner generates executable roadmaps and phases
- **PLAN-04**: Planner integrates with orchestrator to drive multi-phase project execution

### Research Agent

- **RSCH-01**: Agent researches domain ecosystems (stack, features, architecture, pitfalls)
- **RSCH-02**: Agent produces structured research documents for decision-making
- **RSCH-03**: Agent cross-references homelab patterns against best practices

### Voice Interface (Jetson Nano)

- **VOICE-01**: Voice agent runs on Jetson Nano, understands natural speech commands
- **VOICE-02**: Voice agent routes requests to orchestrator, returns spoken responses
- **VOICE-03**: Voice agent replaces Alexa for lab automation queries/commands

### Multi-Project Workspace

- **WS-01**: System tracks multiple concurrent projects, each with own roadmap/phase
- **WS-02**: Resource contention resolved across projects (fair scheduling)
- **WS-03**: Post-mortems cross-project (learn from patterns across multiple efforts)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Post-mortem analysis agent | Scaffolding built in v1, but active analysis/suggestions deferred to v2 when we have execution data |
| Voice interface | Chat/API first. Jetson voice integration requires trained models, planned for v2+ |
| Code generation agent | Focus on infrastructure orchestration in v1. Code agent (write/test/deploy) planned for v2 |
| Research agent | Full research workflows deferred. Can use Claude directly for now if needed |
| Planner agent (full GSD-like) | Using structured chat approval flow initially. GSD-style planner considered for v2 when multi-project needed |
| Multi-project workspace | Single project focus in v1. Multi-project tracking, priority scheduling planned for v2+ |
| Advanced scheduling algorithms | Static agent assignments, manual priority in v1. Queue-based smart scheduling in v2+ |
| Integration with external orchestrators | Kubernetes, Swarm, etc. deferred; Docker + Portainer sufficient for v1 |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ORCH-01 | Phase 3 | Pending |
| ORCH-02 | Phase 3 | Pending |
| ORCH-03 | Phase 5 | Pending |
| ORCH-04 | Phase 5 | Pending |
| ORCH-05 | Phase 3 | Pending |
| STATE-01 | Phase 1, 5 | In Progress |
| STATE-02 | Phase 1 | Pending |
| STATE-03 | Phase 5 | Pending |
| STATE-04 | Phase 5 | Pending |
| MSG-01 | Phase 2 | Complete |
| MSG-02 | Phase 2 | Complete |
| MSG-03 | Phase 2 | Complete |
| MSG-04 | Phase 1, 2 | Complete |
| DESK-01 | Phase 4 | Pending |
| DESK-02 | Phase 4 | Pending |
| DESK-03 | Phase 4 | Pending |
| DESK-04 | Phase 4 | Pending |
| INFRA-01 | Phase 6 | Pending |
| INFRA-02 | Phase 6 | Pending |
| INFRA-03 | Phase 6 | Pending |
| INFRA-04 | Phase 6 | Pending |
| UI-01 | Phase 7 | Pending |
| UI-02 | Phase 7 | Pending |
| UI-03 | Phase 7 | Pending |
| UI-04 | Phase 7 | Pending |
| E2E-01 | Phase 8 | Pending |
| E2E-02 | Phase 8 | Pending |
| E2E-03 | Phase 8 | Pending |
| E2E-04 | Phase 8 | Pending |

**Coverage:**
- v1 requirements: 28 total
- Mapped to phases: 28 (100%)
- Unmapped: 0 ✓

---

*Requirements defined: 2026-01-18*
*Roadmap created: 2026-01-18*
*Last updated: 2026-01-18*
