# Chiffon Architecture

Chiffon is an orchestrated AI agent system designed to autonomously execute infrastructure changes with full auditability, resource awareness, and cost optimization.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interface Layer                      │
│                  (Chat, Web, CLI - Phase 7)                  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│            Orchestrator Service (Phase 3)                    │
│                    (FastAPI)                                 │
│  - Parse user requests                                       │
│  - Plan infrastructure changes                               │
│  - Route work to agents                                      │
│  - Track execution state                                     │
└────────────────┬──────────────────────────┬─────────────────┘
                 │                          │
                 ▼                          ▼
        ┌─────────────────┐      ┌──────────────────┐
        │   RabbitMQ      │      │   PostgreSQL     │
        │  Message Bus    │      │  State Store     │
        │  (Phase 2)      │      │  (Phase 5)       │
        └────┬────────────┘      └──────────────────┘
             │
      ┌──────┴────────┬────────────────┐
      ▼               ▼                ▼
   ┌─────────┐  ┌──────────┐  ┌───────────┐
   │Infrastructure
   │  Agent  │  │ Desktop  │  │   Code    │
   │(Phase 6)│  │  Agent   │  │  Agent    │
   │         │  │(Phase 4) │  │(Future)   │
   │Ansible  │  │ GPU/CPU  │  │           │
   │Playbooks│  │ Metrics  │  │           │
   └────┬────┘  └──────────┘  └───────────┘
        │
        ▼
   External Systems
   (Ansible, Portainer, etc.)
```

## Core Components

### 1. Orchestrator Service

**Location:** `src/orchestrator/`

**Responsibility:** Central coordination hub that:
- Receives user requests in natural language
- Uses LLM (Claude or Ollama) to plan infrastructure changes
- Dispatches work to appropriate agents via RabbitMQ
- Tracks execution state and logs decisions
- Enforces approval gates and cost limits
- Streams execution status back to UI

**Key Endpoints:**
- `POST /request` - Submit infrastructure request
- `GET /request/{id}` - Query request status
- `POST /approve` - User approval for planned work
- `GET /health` - Service health check
- `POST /cancel/{id}` - Cancel pending/running request

**Technology:** FastAPI (async Python web framework)

### 2. RabbitMQ Message Bus

**Location:** Docker service (port 5672)

**Responsibility:** Asynchronous communication layer enabling:
- Loose coupling between orchestrator and agents
- Durable message queues (survives service restarts)
- Reliable message delivery (ACK/NACK pattern)
- Scalability (agents can be added/removed dynamically)

**Topology:**
- Exchange: `chiffon.work` (direct, durable)
- Queues:
  - `orchestrator.requests` - Incoming user requests
  - `agent.infrastructure` - Work for infrastructure agent
  - `agent.desktop.{hostname}` - Desktop agent per-host queues
  - `orchestrator.results` - Results from agents back to orchestrator

**Message Flow:**
1. Orchestrator publishes work_request to agent queue
2. Agent receives, processes, publishes work_status updates
3. Agent publishes work_result when complete
4. Orchestrator receives result, updates PostgreSQL, commits to git

### 3. PostgreSQL Database

**Location:** Docker service (port 5432)

**Responsibility:** Operational state store for:
- Task metadata (what was requested, current status, outcome)
- Execution logs (step-by-step execution history)
- Resource metrics (GPU availability, CPU load, etc.)
- Query-based analytics (post-mortem analysis)

**Key Tables:**
- `tasks` - User requests and their status
- `execution_logs` - Detailed execution history
- `resource_metrics` - Agent resource availability
- `audit_log` - All operational decisions

**Why PostgreSQL:**
- Strong query capabilities for post-mortem analysis
- Full ACID support for consistency
- Easy scaling via replication
- Can join across tables for correlation analysis

### 4. Message Protocol

**Location:** `src/common/protocol.py`

**Message Envelope (JSON):**
```json
{
  "message_id": "uuid-v4",
  "trace_id": "correlation-id",
  "request_id": "original-request-uuid",
  "message_type": "work_request|work_status|work_result|error",
  "timestamp": "2026-01-19T12:34:56Z",
  "version": 1,
  "payload": { ... }
}
```

**Message Types:**

- **work_request:** Orchestrator → Agent
  ```json
  {
    "agent_type": "infrastructure",
    "task_id": "uuid",
    "action": "deploy_kuma",
    "parameters": { "host": "nas", "version": "latest" },
    "resources_required": { "gpu": false, "memory_gb": 2 }
  }
  ```

- **work_status:** Agent → Orchestrator (during execution)
  ```json
  {
    "task_id": "uuid",
    "status": "running",
    "progress": 65,
    "message": "Running Ansible playbook...",
    "metrics": { "cpu": 45.2, "memory": 1024 }
  }
  ```

- **work_result:** Agent → Orchestrator (on completion)
  ```json
  {
    "task_id": "uuid",
    "status": "completed|failed",
    "output": "...",
    "duration_seconds": 120,
    "resource_usage": { "cpu_hours": 0.5, "memory_peak_gb": 2.1 }
  }
  ```

- **error:** Any service → Any service
  ```json
  {
    "code": 5001,
    "message": "...",
    "details": { ... }
  }
  ```

### 5. LiteLLM Service

**Location:** Docker service (port 8001)

**Responsibility:** Vendor-agnostic LLM interface with intelligent fallback:

**Fallback Chain:**
1. **Claude (Anthropic)** - Primary
   - Best reasoning capabilities
   - Uses ANTHROPIC_API_KEY
   - Quota limit: $100/month

2. **GPT-4 (OpenAI)** - Fallback 1
   - Strong general-purpose model
   - Uses OPENAI_API_KEY
   - Quota limit: $50/month
   - Only used if Claude exhausted

3. **Ollama (Local)** - Fallback 2
   - Zero-cost local inference
   - Always available
   - Lower accuracy but reliable

**Configuration:** `config/litellm-config.json`

**Why LiteLLM:**
- Cost optimization: Local LLM before external APIs
- Vendor independence: Easy to swap providers
- Quota management: Prevents runaway API costs
- Fallback reliability: System works offline

### 6. Ollama Service

**Location:** Docker service (port 11434)

**Responsibility:** Local LLM inference for:
- Quick planning decisions
- Cost-sensitive operations
- Offline availability
- Testing without API keys

**Models:**
- Primary: `neural-chat` (balanced capability/speed)
- Alternative: `mistral`, `dolphin-mixtral`

**Lifecycle:**
- First pull: 3-5 minutes, ~2-4GB disk
- Cached locally after first run
- Zero API calls once loaded

## Data Flow

### Complete Workflow Example: Deploy Kuma

```
1. USER REQUEST
   User: "Deploy Kuma Uptime to NAS and add existing portals"
   ↓
2. PARSE REQUEST (Orchestrator)
   - Extract intent: deploy Kuma, discover existing config
   - Determine required capabilities: infrastructure agent
   ↓
3. PLAN WORK (Orchestrator + LiteLLM)
   - LiteLLM queries Claude: "Plan this Kuma deployment"
   - Returns: [step_1, step_2, step_3] with estimates
   - Cost estimate: $0.02 in external API calls
   ↓
4. PRESENT TO USER (UI)
   - Show plan: "Will: download Kuma, update docker-compose, restart services"
   - Get approval
   ↓
5. DISPATCH WORK (Orchestrator → RabbitMQ)
   - Create Task record in PostgreSQL
   - Publish work_request to infrastructure agent queue
   ↓
6. EXECUTE (Infrastructure Agent)
   - Receive work_request from RabbitMQ
   - Run Ansible playbook: roles/kuma-deploy/main.yml
   - Publish work_status updates (progress, logs)
   - Track resource usage (CPU, memory, runtime)
   ↓
7. STREAM RESULTS (Agent → Orchestrator → UI)
   - Ansible output streamed in real-time
   - Status updates via work_status messages
   - UI shows live progress
   ↓
8. RECORD OUTCOME (Orchestrator)
   - Receive work_result from agent
   - Update Task status in PostgreSQL
   - Commit to git: "infra(task-uuid): Deploy Kuma to NAS"
   - Audit log: success, duration, resources
   ↓
9. AUDIT TRAIL
   - `git log` shows infrastructure changes
   - PostgreSQL query reveals execution timeline
   - Resource metrics available for cost analysis
```

## Why This Architecture

### 1. Loose Coupling

**Problem:** Tightly coupled systems fail as a unit

**Solution:** RabbitMQ message bus
- Orchestrator doesn't know agent internals
- Agents can be restarted, replaced, scaled independently
- Easy to add new agent types (Code Agent, Researcher, etc.)

### 2. Auditability

**Problem:** Silent failures make troubleshooting hard

**Solution:** PostgreSQL + Git dual logging
- PostgreSQL: Real-time queries, analytics, joins
- Git: Immutable historical archive, blame tracking, rollback capability

**Example Use Case:** Post-mortem analysis
- "Why did this task fail?" → Query PostgreSQL execution_logs
- "Who made this change?" → `git blame` + `git log`
- "What changed over time?" → Git history + diff

### 3. Cost Awareness

**Problem:** Unlimited external API calls → $1000+ bills

**Solution:** Multi-tier LLM strategy
- Local Ollama (free) for routine planning
- Claude (efficient) for complex reasoning
- Quota tracking: triggers fallback at thresholds
- PostgreSQL logs costs for billing + alerts

### 4. Resource Awareness

**Problem:** Blindly dispatch work → GPU bottleneck

**Solution:** Desktop agent heartbeat metrics
- Agents report CPU/GPU/memory periodically
- Orchestrator queries metrics before dispatch
- Work queued/paused based on availability

### 5. Integration Over Replacement

**Problem:** Rewriting existing infrastructure is risky

**Solution:** Wrap existing tools
- Infrastructure Agent wraps Ansible (keeps your expertise)
- Agents orchestrate, don't replace
- Familiar tools + new automation layer

## Technology Choices

| Component | Technology | Why |
|-----------|-----------|-----|
| Orchestrator | FastAPI (Python) | Async, auto-OpenAPI docs, compatible with GSD |
| Message Bus | RabbitMQ | Mature, HA support, durable queues |
| State Store | PostgreSQL | ACID, query-friendly, replication |
| LLM Proxy | LiteLLM | Multi-provider, quota mgmt, fallback |
| Local LLM | Ollama | Fast, zero-cost, runs anywhere |
| IaC Integration | Ansible | Already in use, mature ecosystem |

## Deployment Architecture

### Phase 1 (Foundation)
- All services in Docker (dev/test)
- Single orchestrator instance
- Local database

### Phase 2-5 (Core)
- RabbitMQ topology established
- PostgreSQL as operational store
- Git as audit trail

### Phase 6+ (Production)
- PostgreSQL replication (HA)
- Multiple orchestrator instances (load balanced)
- RabbitMQ clustering
- Dedicated agent deployment nodes

## Error Handling

Every error in the protocol includes:
- Unique error code (5001-5999)
- Human-readable message
- Machine-readable details
- Trace ID for debugging

**Error Recovery:**
- Transient errors: Automatic retry with backoff
- Permanent errors: Recorded in PostgreSQL, alerted via UI
- Resource exhaustion: Queue work until available

## Testing Strategy

- **Unit Tests:** Protocol models, message serialization
- **Integration Tests:** Orchestrator + mock agents
- **Contract Tests:** Message format compliance
- **E2E Tests:** Full workflow (Phase 8)

## Scaling

### Current (Phase 1)
- Single orchestrator: ~10 concurrent requests

### Medium (Phase 3-5)
- Multiple orchestrators behind load balancer: ~100 requests
- Agent fleet scales to 10+ machines

### Large (v2)
- Event-sourced state model
- Multi-datacenter orchestrators
- Partitioned PostgreSQL
- Message bus clustering

## See Also

- [SETUP.md](SETUP.md) - Development environment setup
- [PROTOCOL.md](PROTOCOL.md) - Detailed message format specification
- [REQUIREMENTS.md](../REQUIREMENTS.md) - v1 requirements mapping
- [ROADMAP.md](../.planning/ROADMAP.md) - Phase breakdown and timeline

---

**Last Updated:** 2026-01-19
**Status:** Phase 1 Foundation Complete
**Next:** Phase 2 Message Bus Integration
