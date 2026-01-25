# Phase 4: Desktop Agent - Context

**Gathered:** 2026-01-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Lightweight agents run on GPU desktops and report real-time resource availability (CPU load, GPU VRAM, available CPU cores) to the orchestrator. Agents signal online/offline status via heartbeat messages, allowing the orchestrator to query capacity before dispatching work. Agent installation and resource metrics accuracy are in scope; work execution is Phase 6 (Infrastructure Agent).

</domain>

<decisions>
## Implementation Decisions

### Resource Metrics Accuracy
- **GPU VRAM measurement:** Claude's Discretion — use nvidia-smi or system reporting as appropriate
- **CPU load reporting:** Report rolling averages (1-min, 5-min load average) rather than instantaneous load for stable scheduling decisions
- **CPU core counting:** Report physical cores only (not logical cores with hyperthreading) to be conservative with capacity
- **Available cores calculation:** Calculate available cores from CPU load percentage (if 50% load on 8 cores, report ~4 cores available), not total-minus-active

### Heartbeat Strategy
- **Heartbeat interval & timeout:** Claude's Discretion — defaults are 30s interval and 90s offline threshold, but can be tuned without phase re-planning
- **Offline detection resilience:** Require 2-3 consecutive missed heartbeats before marking agent offline (tolerate brief network disruptions)
- **Graceful shutdown:** Agent attempts graceful shutdown notification to orchestrator; orchestrator uses timeout-based detection as fallback
- **Heartbeat metadata:** Claude's Discretion — include sequence number or timestamp if helpful for debugging; keep optional

### Agent Startup & Registration
- **Registration on startup:** Claude's Discretion — balance between auto-register (trust) and manual approval; homelab context supports auto-register with monitoring
- **Agent identification:** Use both hostname (human-readable display name) and UUID (stable unique identifier)
- **Configuration source:** Read from config file (YAML/JSON) at ~/.chiffon/agent.yml or /etc/chiffon/agent.yml; env vars can override
- **Persistent local state:** Agent stores config and state (agent_id, registration timestamp) in local file; survives restarts with consistent identity
- **RabbitMQ connection on startup:** Retry N times (recommend 10) then exit; prevents zombie processes; forced restart when network recovers
- **Startup validation:** Perform basic validation only (check RabbitMQ connectivity, GPU driver availability); warn on issues but don't block startup

### Metrics Data Format
- **Historical data in heartbeats:** Current state only (no peak/min trends in each message); orchestrator can aggregate history if needed
- **System metadata:** Include GPU model, CPU specs, OS version during registration; subsequent heartbeats contain only agent_id and current metrics
- **Metric values format:** Raw values (GB for VRAM, core count for CPU, load count for CPU) rather than normalized percentages
- **Diagnostic metrics:** Minimal resource-only metrics (CPU load, GPU VRAM, cores); temperature, fans, process lists deferred unless debugging needs arise

### Claude's Discretion
- GPU VRAM measurement approach (nvidia-smi vs system APIs)
- Whether to include sequence numbers/timestamps in heartbeats
- Auto-register vs manual approval registration policy
- Configurable defaults for heartbeat timing without requiring phase re-plan

</decisions>

<specifics>
## Specific Ideas

No specific product references or implementation examples were discussed. The phase focuses on reliable resource reporting and heartbeat reliability for orchestrator dispatch decisions.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. Historical metric aggregation and advanced diagnostics (thermal, process-level) noted as future enhancements beyond v1.

</deferred>

---

*Phase: 04-desktop-agent*
*Context gathered: 2026-01-19*
