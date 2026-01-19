# Chiffon: Orchestrated AI Agents for Homelab Automation

## What This Is

A local agentic orchestration platform that automates infrastructure deployment, code generation, and testing across a home lab environment. Users request work via natural language (chat, eventually voice), the system plans execution, coordinates multiple AI agents, manages resource constraints (GPU availability, API quotas), and maintains an immutable audit trail for post-mortem analysis and continuous improvement.

## Core Value

**Autonomous delivery of infrastructure changes and features with full visibility, approval gates, and cost optimization.**

Everything else can fail. This must work: users can request infrastructure work, the system executes it with auditability and cost awareness, and failures are logged for analysis and workflow improvement.

## Requirements

### Validated

(None yet — proving the orchestrator model with Kuma deployment example in v1)

### Active

#### Orchestrator Core
- [ ] **ORCH-01**: Orchestrator accepts natural language requests and structures them into work plans
- [ ] **ORCH-02**: Orchestrator dispatches work to appropriate agent (infra, code, research, etc.) via message queue
- [ ] **ORCH-03**: Orchestrator tracks execution state in PostgreSQL with audit trail commits to git
- [ ] **ORCH-04**: Orchestrator pauses/resumes execution based on available GPU resources on desktop agents
- [ ] **ORCH-05**: Orchestrator falls back to external AI (Claude) when: local quota <20%, task requires complex reasoning, or work marked high-value

#### State & Audit
- [ ] **STATE-01**: All decisions and execution results committed to git (immutable audit trail)
- [ ] **STATE-02**: PostgreSQL schema tracks task status, outcomes, resources used, timestamps
- [ ] **STATE-03**: Audit logs support querying: "all failures in last week", "all changes to service X"
- [ ] **STATE-04**: Scaffolding exists for future post-mortem agent (structured failure logs, optimization suggestions)

#### Message Bus & Communication
- [ ] **MSG-01**: RabbitMQ-based message queue for agent dispatch
- [ ] **MSG-02**: Agents receive work via MQ, send status updates back
- [ ] **MSG-03**: REST API for orchestrator queries and manual operations
- [ ] **MSG-04**: Agent protocol defined and documented (message format, error handling, timeouts)

#### Desktop Agent (Resource Awareness)
- [ ] **DESK-01**: Lightweight agent runs on each GPU desktop, reports load percentage
- [ ] **DESK-02**: Desktop agent reports available GPU VRAM, CPU cores
- [ ] **DESK-03**: Desktop agent signals online/offline status to orchestrator
- [ ] **DESK-04**: Orchestrator can query desktop agent for work capacity before dispatch

#### Infrastructure Agent (Ansible Integration)
- [ ] **INFRA-01**: Infra agent accepts deployment tasks and maps them to existing Ansible playbooks
- [ ] **INFRA-02**: Infra agent executes playbooks and streams output back to orchestrator
- [ ] **INFRA-03**: Infra agent suggests improvements to playbooks (new patterns, automation opportunities)
- [ ] **INFRA-04**: Infra agent generates new playbook templates for common tasks (service deployment, config updates)

#### User Interface & Approval
- [ ] **UI-01**: Chat interface accepts deployment requests in natural language
- [ ] **UI-02**: Orchestrator presents execution plan to user for approval
- [ ] **UI-03**: User can approve, reject, or request modifications to plan before execution
- [ ] **UI-04**: Execution log shows all steps, outputs, and decisions for transparency

#### Integration & End-to-End
- [ ] **E2E-01**: Full workflow: user requests "Deploy Kuma Uptime, add existing portals to config"
- [ ] **E2E-02**: System finds existing Kuma configs/playbooks in ~/CascadeProjects/homelab-infra
- [ ] **E2E-03**: Infra agent deploys container, configures service, suggests playbook updates
- [ ] **E2E-04**: Updates committed to git, state recorded in DB, user reviews audit trail

### Out of Scope

- **Post-mortem analysis agent** — Scaffolding built in v1, but analysis/suggestions deferred to v2
- **Voice interface** — Chat/API first, Jetson voice integration in v2+
- **Code generation agent** — Focus on infra in v1; code agent (write/test/deploy) planned for v2
- **Research agent** — Full research workflows deferred; can use Claude directly for now
- **Planner agent** — Using structured chat approval flow initially; GSD-like planner considered for v2
- **Multi-project workspace** — Single project focus in v1; multi-project tracking in v2+

## Context

**Existing Homelab:**
- Primary: Unraid server (storage, services coordination)
- Compute: 2 Proxmox nodes (DNS, DHCP, LXC containers)
- GPU Workers: 3 Windows desktops with NVIDIA GPUs (containerized workloads)
- Orchestration: Portainer (Docker agent model) + Ansible (IaC)
- Infrastructure as Code: ~/CascadeProjects/homelab-infra (Ansible playbooks, docker-compose stacks, Git as source of truth)

**Inspiration & Philosophy:**
- GSD (Get-Shit-Done) patterns: structured project context, auditable decisions, phase-gated execution
- Cost optimization: run locally when possible, external AI for high-value tasks or burst capacity
- Resource awareness: respect GPU desktop availability, pause work during peak usage (gaming)
- Auditability: every decision and execution result persists for analysis and improvement

**Problem Being Solved:**
- Manual infrastructure changes are error-prone and hard to audit
- GPU desktop availability is variable; workloads need intelligent scheduling
- Frequent manual patterns (e.g., adding new services) could be automated
- No visibility into what changed, when, and why across the lab
- Cost of running external AI is high; local + external hybrid is more sustainable

## Constraints

- **Infrastructure**: Existing ansible/docker-compose tooling; agent must integrate, not replace
- **Team**: Solo developer (you); system must be operationally simple initially
- **Cost**: Minimize external AI calls; local Ollama/llama.cpp for base models, Claude for complex reasoning
- **Deployment**: Run agents in Docker across lab; prefer containerized over complex local setup
- **GPU Availability**: Variable; desktop agents may be offline during gaming hours
- **Learning**: Build incrementally; v1 proves orchestrator + infra agent, later tiers add complexity

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Start with Orchestrator + Infra Agent only | Proof-of-concept: resource-aware dispatch + infrastructure integration. Avoids boiling ocean with full planner/researcher/etc | — Pending |
| Git + PostgreSQL state model | Git for immutable audit trail (commits), PostgreSQL for real-time state + queries. Enables post-mortems + auditability | — Pending |
| RabbitMQ + FastAPI stack | Battle-tested async dispatch; Python ecosystem (GSD compatibility). Simpler than gRPC, more robust than git-polling | — Pending |
| Desktop agents report resource status | Real-time accuracy on GPU availability. Enables intelligent scheduling, avoids failed task dispatch | — Pending |
| Wrap existing Ansible playbooks | Reuse infrastructure patterns already working; infra agent orchestrates, not rewrites | — Pending |
| Chat interface for v1 approval | Manual gates initially build confidence. Auto-approval in later phases as workflows proven | — Pending |

---
*Last updated: 2026-01-18 after initialization questioning*
