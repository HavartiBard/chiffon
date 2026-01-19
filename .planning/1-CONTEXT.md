# Phase 1: Foundation — Implementation Context

**Phase:** 1 - Foundation & Observability Infrastructure
**Created:** 2026-01-18
**Status:** Ready for planning

---

## Executive Summary

Phase 1 builds the technical foundation: PostgreSQL schema for operational state tracking, agent protocol specification, Docker local dev environment, and LiteLLM integration for vendor-agnostic LLM access. Git holds long-term context and infrastructure-as-code; PostgreSQL handles all daily operations.

**Key insight:** PostgreSQL is operational (queries, traceability), Git is reference (context, code, IaC).

---

## PostgreSQL Schema Design

### Philosophy
- Separate concerns: tasks table (what was requested), execution_logs table (what happened)
- Multi-project ready from day one (even though v1 is single-project execution)
- Query-optimized for post-mortem analysis

### Tables

**tasks**
```
- task_id (UUID, PK)
- project_id (UUID, FK - for v2 multi-project)
- request_text (TEXT - the user's natural language request)
- status (ENUM: pending, approved, executing, completed, failed, rejected)
- created_at (TIMESTAMP)
- created_by (user reference - optional for v1)
- approved_at (TIMESTAMP)
- completed_at (TIMESTAMP)
- estimated_resources (JSONB - duration, GPU VRAM, CPU cores estimate)
- actual_resources (JSONB - duration, GPU VRAM used, CPU time, external_ai_calls)
- external_ai_used (JSONB - which providers, token count per provider, costs)
- error_message (TEXT - if failed)
```

**execution_logs**
```
- log_id (UUID, PK)
- task_id (UUID, FK)
- step_number (INT - order of execution)
- agent_type (ENUM: orchestrator, infra, code, research, desktop, etc.)
- action (TEXT - what the agent did)
- status (ENUM: running, completed, failed)
- output_summary (TEXT - first 500 chars for quick review)
- output_full (JSONB - raw agent output as blob, or reference to external storage if huge)
- timestamp (TIMESTAMP)
- duration_ms (INT)
```

### Indexing Strategy
- `tasks(created_at)` - fast filtering by timeframe for post-mortems
- `tasks(status)` - quick failure/completion queries
- `execution_logs(task_id)` - fetch all steps for a task
- No index on `request_text` unless search needed

### Data Retention
- Keep live in PostgreSQL: last 6 months
- Older tasks archived to JSON files in git (read-only historical reference)
- Archival script runs monthly, removes from DB, commits to git history

### Schema Versioning
- Use Alembic (Python migration tool)
- Migrations live in `migrations/` directory, versioned in git
- Each schema change is a new numbered migration (001_init.py, 002_add_external_ai.py, etc.)
- Migration scripts track in git, replay on new deployments

### Sample Data
- Phase 1 includes seed script to populate sample tasks + execution_logs for testing
- Allows verification of post-mortem queries before real data exists
- Seed data deleted during Phase 1 cleanup

### Bootstrap Query Examples (for success criteria validation)
```sql
-- All failed tasks in last week
SELECT * FROM tasks WHERE status = 'failed' AND created_at > NOW() - INTERVAL '7 days';

-- Task execution timeline
SELECT task_id, step_number, agent_type, action, status, duration_ms FROM execution_logs WHERE task_id = 'xxx' ORDER BY step_number;

-- Resource usage analysis
SELECT task_id, actual_resources->>'external_ai_calls' FROM tasks WHERE created_at > NOW() - INTERVAL '1 month';
```

---

## Git Strategy (Revised)

### Philosophy
**Git = Long-term context + Infrastructure-as-Code only. PostgreSQL = Daily operational state.**

This decouples version control from operational overhead.

### What Lives in Git
- **Project context:** PROJECT.md, ROADMAP.md, REQUIREMENTS.md, STATE.md (project structure)
- **Infrastructure-as-Code:** Ansible playbooks, Docker Compose stacks, LiteLLM config
- **Code:** Orchestrator service, agents, utilities
- **Historical archive:** Encrypted backups of old PostgreSQL data (monthly, automated)

### What Does NOT Live in Git
- ✗ Daily audit commits (operational noise)
- ✗ Playbook discovery state (cached in PostgreSQL)
- ✗ Execution logs (PostgreSQL is source of truth)
- ✗ Deployment tracking (PostgreSQL queries)

### Playbook Improvements Workflow
1. Infra agent suggests improvement: logged to PostgreSQL with suggested playbook code
2. You review in PostgreSQL (not git)
3. When approved, you manually merge improvement to homelab-infra repo
4. Creates PR or direct commit in homelab-infra — your workflow

### No Daily Commits
- Eliminates git as operational bottleneck
- Removes external dependency from daily orchestrator operations
- Playbook discovery happens at startup + periodic refresh, not per-task

---

## Agent Protocol Specification

### Message Format: JSON Envelope

**Base Envelope (all messages)**
```json
{
  "protocol_version": "1.0",
  "message_id": "msg-uuid-1234",
  "from_agent": "orchestrator|infra|desktop|code|research",
  "to_agent": "orchestrator|infra|desktop|code|research",
  "timestamp": "2026-01-18T15:30:00Z",
  "trace_id": "trace-uuid-5678",
  "request_id": "req-uuid-9999",
  "type": "work_request|work_status|work_result|error",
  "payload": { /* type-specific */ },
  "x_custom_fields": {} /* vendor extensions */
}
```

### Message Types

**work_request** (Orchestrator → Agent)
```json
{
  "type": "work_request",
  "payload": {
    "task_id": "task-uuid",
    "work_type": "deploy_service|run_playbook|etc",
    "parameters": { /* task-specific */ },
    "hints": {
      "max_duration_seconds": 300,
      "suggested_max_memory_mb": 2048
    }
  }
}
```

**work_status** (Agent → Orchestrator, during execution)
```json
{
  "type": "work_status",
  "payload": {
    "task_id": "task-uuid",
    "status": "running|step_completed",
    "progress_percent": 45,
    "step": {
      "number": 2,
      "name": "Deploy container",
      "output": "Container started with ID abc123..."
    }
  }
}
```

**work_result** (Agent → Orchestrator, final)
```json
{
  "type": "work_result",
  "payload": {
    "task_id": "task-uuid",
    "status": "success|failed",
    "exit_code": 0,
    "output": "Full execution output here",
    "resources_used": {
      "duration_seconds": 120,
      "gpu_vram_mb": 4096,
      "cpu_time_ms": 15000
    }
  }
}
```

**error** (Either direction)
```json
{
  "type": "error",
  "payload": {
    "error_code": 5001,
    "error_message": "Connection timeout to orchestrator",
    "error_context": {
      "attempted_retries": 3,
      "last_attempt": "2026-01-18T15:30:00Z"
    }
  }
}
```

### Error Codes (Reserved for v1)
```
5001 - Timeout
5002 - Agent unavailable
5003 - Invalid message format
5004 - Authentication failed
5005 - Resource limit exceeded
5006 - Unsupported work type
5xxx - Agent-specific errors (5100-5199 for infra, 5200-5299 for desktop, etc.)
```

### Reliability & Resilience

**Timeouts**
- Default: 30 seconds for agent response
- Orchestrator waits 30s for acknowledgment
- If no response, begins retry backoff

**Retries**
- Max 3 retries per message
- Exponential backoff: 1s, 2s, 4s delays between retries
- After 3 failed retries: task marked failed, logged

**Idempotency**
- Each message includes `request_id`
- Agent checks if `request_id` already seen
- If seen: returns cached result instead of re-executing
- Prevents duplicate work on retries

**Circuit Breaker**
- Track agent failures
- After 5 consecutive failures: circuit opens, orchestrator stops routing to that agent for 60 seconds
- Agent can rejoin after heartbeat received
- Prevents cascading failures

**Large Payloads**
- Outputs >1MB chunked across multiple `work_status` messages
- Agent streams output in 256KB chunks
- Orchestrator reassembles on receiving all chunks
- Prevents RabbitMQ overload

### Versioning & Compatibility
- `protocol_version` in every message
- Current: `1.0`
- Agents register their supported versions on connect
- Orchestrator negotiates: uses lowest common version
- Allows forward/backward compatibility for v2+

### Authentication
- Bearer token per agent in Authorization header (or message field for MQ)
- Token: 32-char random string, stored in config.json
- Orchestrator validates token on every message
- Token rotation handled during Phase 2 (not in Phase 1 scope)

### Documentation & Testing
- **OpenAPI spec:** `docs/agent-protocol.yaml` (machine-readable, auto-generates Swagger UI)
- **Markdown guide:** `docs/PROTOCOL.md` (human-readable examples)
- **Contract tests:** `tests/protocol_contract_test.py` validates all agents conform to spec
- Runs as part of CI/CD, catches protocol drift

---

## LiteLLM Integration (Vendor-Agnostic LLM Access)

### Philosophy
**Single unified LLM proxy layer. Agents never call Claude/OpenAI/Gemini directly.**

### LiteLLM Deployment
- Deployed in Phase 1 as foundation Docker service
- Runs as FastAPI wrapper around LiteLLM Python library
- Exposes standard `/v1/chat/completions` endpoint (OpenAI-compatible)

### Configuration (config.json)
```json
{
  "litellm": {
    "default_model": "claude-opus",
    "fallback_strategy": [
      "claude-opus-4.5",
      "gpt-4-turbo",
      "ollama/neural-chat"
    ],
    "quota_limits": {
      "claude": {
        "monthly_limit_usd": 100,
        "fallback_after_80_percent": true
      },
      "gpt4": {
        "monthly_limit_usd": 50,
        "fallback_after_80_percent": true
      }
    },
    "api_keys": {
      "ANTHROPIC_API_KEY": "{{ env.ANTHROPIC_API_KEY }}",
      "OPENAI_API_KEY": "{{ env.OPENAI_API_KEY }}"
    }
  }
}
```

### Routing Logic
1. Request comes in from agent to LiteLLM endpoint
2. LiteLLM checks quota for primary model (Claude)
3. If Claude quota < 20% remaining: use fallback (GPT-4)
4. If GPT-4 quota also low: use local (Ollama)
5. Log to separate LiteLLM log file: model used, tokens, cost

### Cost Tracking
- **LiteLLM logs:** Separate from orchestrator logs (not in PostgreSQL initially)
- **Format:** JSON lines, one entry per LLM call
- **Fields:** timestamp, model, input_tokens, output_tokens, cost_usd, agent_requesting, task_id
- You review costs manually; could integrate with PostgreSQL in Phase 2

### Local Fallback
- Ollama running in Docker container (same compose stack as PostgreSQL)
- Default model: `neural-chat` or similar for general purpose tasks
- Fast responses (no API latency), zero cost
- May be slower/less capable than Claude, but appropriate for routine planning

### No Vendor Lock-in
- Swap providers by updating config.json
- Agents don't care which LLM backs the endpoint
- Easy to benchmark: "what if we used GPT-4 instead?"

---

## Docker & Development Environment

### Local Development Stack

**docker-compose.yml (Phase 1)**
```
Services:
- postgres:15 (database)
- rabbitmq:management (message queue)
- ollama (local LLM fallback)
- litellm (LLM proxy service)
- orchestrator (FastAPI service, runs locally in dev)
```

**Why this stack?**
- All services self-contained, reproducible
- Same stack runs on Unraid in production
- Zero external dependencies for local dev (except LLM APIs)

### Python Environment
- **Python version:** 3.11+
- **Dependency manager:** Poetry (pyproject.toml + poetry.lock)
- **Key packages:** fastapi, sqlalchemy, pydantic, pika (RabbitMQ), alembic (migrations)

### Code Quality
- **Testing:** pytest (tests/ directory)
- **Linting/Formatting:** black for formatting, ruff for linting (configured in pyproject.toml)
- **Type checking:** mypy optional (recommended but not blocking in v1)
- **Test coverage:** Aim for 70%+ on core modules

### Secrets Management (Phase 1 Placeholder)
- **.env.example** file committed to git (shows required vars, no values)
- **.env** file (actual secrets) in .gitignore locally
- Phase 1 uses: `python-dotenv` loads .env on startup
- **Future phase (TBD):** Integrate with Ansible vault or LiteLLM secret backend
- For now: assume secrets are populated somehow (manual or via CI)

### Project Structure
```
agent-deploy/
├── .planning/                    # GSD planning artifacts
│   ├── PROJECT.md
│   ├── REQUIREMENTS.md
│   ├── ROADMAP.md
│   ├── STATE.md
│   └── 1-CONTEXT.md
├── docs/
│   ├── PROTOCOL.md              # Protocol examples
│   ├── agent-protocol.yaml      # OpenAPI spec
│   └── SETUP.md
├── src/
│   ├── orchestrator/            # Main service
│   │   ├── __init__.py
│   │   ├── main.py
│   │   └── ...
│   ├── agents/                  # Agent base classes (Phase 2)
│   └── common/                  # Shared utilities
├── tests/
│   ├── protocol_contract_test.py
│   └── ...
├── migrations/                  # Alembic schema migrations
│   └── versions/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

### Getting Started (Dev)
```bash
# Install dependencies
poetry install

# Start services
docker-compose up -d

# Run migrations
poetry run alembic upgrade head

# Load sample data
poetry run python scripts/load_sample_data.py

# Run tests
poetry run pytest

# Start orchestrator (dev mode)
poetry run uvicorn src.orchestrator.main:app --reload
```

---

## Homelab Integration

### Repository Structure
- **agent-deploy:** Separate repo (this project)
- **homelab-infra:** Existing repo with Ansible playbooks + Docker stacks

Both are independent; agent-deploy references homelab-infra.

### Playbook Discovery
- **At Phase 1 completion:** Infra agent (built later) will clone homelab-infra, scan for playbooks
- **For Phase 1:** Manual configuration of available playbooks (just document the layout)
- **Caching strategy:** Playbook list cached locally with 1-hour TTL
- **Refresh trigger:** Manual refresh via API call, or automatic on agent restart

### Playbook Patterns & Conventions
- Phase 1 documents homelab-infra pattern assumptions (role structure, naming, handlers)
- Agent will follow these patterns when generating new playbooks
- Example: "Playbooks use role-based organization: roles/*, tasks/site.yml"
- Agent suggests improvements to patterns but doesn't enforce them

### Improvement Workflow
1. Infra agent executes playbook from homelab-infra
2. Agent analyzes results, suggests improvement: "Add health check handler"
3. Improvement logged to PostgreSQL (orchestrator stores it)
4. You review in PostgreSQL UI or API
5. When approved, you manually update homelab-infra and commit
6. Next time agent runs, it sees the improvement in codebase

**No automatic PRs in v1** — You maintain control over homelab-infra changes.

### Git Credentials
- SSH key or GitHub token stored in .env
- Used for cloning homelab-infra read-only
- PR creation (future): will use same credentials

### Deployment Tracking
- When infra agent executes playbook from homelab-infra version X
- Result logged to PostgreSQL with: playbook_name, homelab_infra_commit_hash, task_id, success/failure
- Enables query: "Which playbook version was deployed when?"
- Git history implicit (you can `git log` homelab-infra to correlate)

---

## Success Criteria (Phase 1 Completion)

✓ PostgreSQL deployed, schema initialized, sample queries work
✓ Git repository ready (project structure, no operational logs)
✓ Agent protocol spec written (OpenAPI + markdown), contract tests included
✓ Docker Compose runs all foundation services
✓ LiteLLM configured with fallback chain (Claude → GPT-4 → Ollama)
✓ Project structure established (src/, tests/, migrations/, docs/)
✓ Development environment: poetry, pytest, black, ruff configured
✓ Sample data loaded for testing post-mortem queries
✓ Documentation: SETUP.md, PROTOCOL.md complete
✓ Homelab-infra playbook patterns documented

---

## Known Unknowns / Deferred Decisions

| Item | Status | Why Deferred |
|------|--------|------------|
| Secrets management strategy | Phase X TBD | Need to design Ansible vault or LiteLLM integration separately |
| Protocol authentication (tokens) | Placeholder | Phase 2: add token rotation, expiry |
| Real-time playbook refresh | 1h cache | Could be made faster later if needed |
| Automatic PR creation | Manual only | v1: you approve before PR, future: fully autonomous |
| PostgreSQL backup strategy | Daily Ansible | Detail in Phase 1 planning |
| Local LLM performance | Unknown | May need fallback to Claude more often than anticipated |

---

## Blocked By

None. Ready for Phase 1 planning.

---

**Context ready for `/gsd:plan-phase 1`**
