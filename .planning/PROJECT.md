# Chiffon: Orchestrated AI Agents for Homelab Automation

## What This Is

A local agentic orchestration platform that automates infrastructure deployment, code generation, and testing across a home lab environment. Users request work via natural language (chat, eventually voice), the system plans execution, coordinates multiple AI agents, manages resource constraints (GPU availability, API quotas), and maintains an immutable audit trail for post-mortem analysis and continuous improvement.

## Core Value

**Autonomous delivery of infrastructure changes and features with full visibility, approval gates, and cost optimization.**

Everything else can fail. This must work: users can request infrastructure work, the system executes it with auditability and cost awareness, and failures are logged for analysis and workflow improvement.

## Current State: v1.0 Complete

**Status:** ✅ SHIPPED 2026-01-22

All 28 v1 requirements delivered and validated:
- Orchestrator: NL request → planning → agent dispatch ✓
- Infrastructure Agent: Playbook discovery, execution, suggestions ✓
- Desktop agents: Real-time resource reporting ✓
- State tracking: PostgreSQL + git audit trail ✓
- Dashboard: Chat interface, approval workflow, monitoring ✓
- E2E validation: Kuma deployment scenario tested ✓

See `.planning/milestones/v1.0-ROADMAP.md` and `v1.0-REQUIREMENTS.md` for full completion details.

## Requirements

### Validated (v1.0 Shipped)

- ✓ **ORCH-01**: Orchestrator accepts NL requests → work plans — v1.0
- ✓ **ORCH-02**: Work dispatch to agents via RabbitMQ — v1.0
- ✓ **ORCH-03**: Execution state tracking (PostgreSQL + git) — v1.0
- ✓ **ORCH-04**: Pause/resume on capacity constraints — v1.0
- ✓ **ORCH-05**: External AI fallback (quota <20%) — v1.0
- ✓ **STATE-01**: Git immutable audit trail — v1.0
- ✓ **STATE-02**: PostgreSQL task schema — v1.0
- ✓ **STATE-03**: Audit querying (time, service, status) — v1.0
- ✓ **STATE-04**: Post-mortem scaffolding — v1.0
- ✓ **MSG-01**: RabbitMQ topology — v1.0
- ✓ **MSG-02**: Agent message protocol — v1.0
- ✓ **MSG-03**: REST API (4 endpoints) — v1.0
- ✓ **MSG-04**: Agent protocol documentation — v1.0
- ✓ **DESK-01**: Desktop agent resource reporting — v1.0
- ✓ **DESK-02**: GPU VRAM + CPU cores metrics — v1.0
- ✓ **DESK-03**: Online/offline status — v1.0
- ✓ **DESK-04**: Capacity queries before dispatch — v1.0
- ✓ **INFRA-01**: Playbook discovery + mapping — v1.0
- ✓ **INFRA-02**: Playbook execution + streaming — v1.0
- ✓ **INFRA-03**: Improvement suggestions — v1.0
- ✓ **INFRA-04**: Template generation (Jinja2) — v1.0
- ✓ **UI-01**: Chat interface — v1.0
- ✓ **UI-02**: Plan presentation — v1.0
- ✓ **UI-03**: Approval workflow — v1.0
- ✓ **UI-04**: Execution monitoring — v1.0
- ✓ **E2E-01**: Full workflow request → audit — v1.0
- ✓ **E2E-02**: Config discovery — v1.0
- ✓ **E2E-03**: Deployment execution — v1.0
- ✓ **E2E-04**: Audit trail complete — v1.0

### Active (v1.1 Planned)

- [ ] **AUTO-APPROVE**: Auto-approval for trusted patterns (without manual gate)
- [ ] **MULTI-ORCHESTRATOR**: Coordinate multiple orchestrator instances
- [ ] **PERFORMANCE**: Optimize local LLM caching and batch requests
- [ ] **MORE-AGENTS**: Extend agent types (research, code generation)
- [ ] **PLAYBOOK-LIBRARY**: Expand playbook support beyond Kuma

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

| Decision | Rationale | Outcome | Status |
|----------|-----------|---------|--------|
| Orchestrator + Infra Agent only | Proof-of-concept: resource-aware dispatch + infrastructure. Avoid complexity. | ✓ Works well; foundation for v2 agents | ✓ Complete |
| Git + PostgreSQL state model | Immutable audit (git) + real-time queries (DB). Enables post-mortems. | ✓ Enables full traceability; audit queries working | ✓ Complete |
| RabbitMQ + FastAPI stack | Async dispatch, Python ecosystem. Simpler than gRPC. | ✓ Agent framework reusable; message protocol v1.0 | ✓ Complete |
| Desktop agents report resources | Real-time GPU availability. Intelligent scheduling. | ✓ Multi-agent tracking working; 90s offline threshold | ✓ Complete |
| Wrap existing Ansible playbooks | Reuse existing patterns; agent orchestrates, not rewrites. | ✓ Playbook discovery + execution integration complete | ✓ Complete |
| Chat interface for v1 approval | Manual gates build confidence initially. Auto-approval in v1.1. | ✓ User workflow intuitive; suggestions working | ✓ Complete |
| FAISS semantic matching | Fast playbook discovery without exact match requirement. | ✓ 0.85 confidence threshold prevents false positives | ✓ Complete |
| Jinja2 template generation | Industry standard for Ansible. Produces clean playbooks. | ✓ Galaxy-compliant templates generating correctly | ✓ Complete |

---

## v1.0 Validation

**Shipment Date:** 2026-01-22
**Total Development:** 4 days (2026-01-19 to 2026-01-22)
**Code Written:** ~17,000 lines (Python + TypeScript)
**Test Coverage:** 1,200+ tests (100% passing)
**Requirements:** 28/28 validated (100%)

**System Status:** ✓ PRODUCTION READY
**Kuma Deployment Scenario:** ✓ END-TO-END VALIDATED

---
*Last updated: 2026-01-22 after v1.0 milestone completion*
