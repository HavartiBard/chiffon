# Chiffon: Orchestrated AI Agents for Homelab Automation

Autonomous delivery of infrastructure changes and features with full visibility, approval gates, and cost optimization.

## Quick Links

- **[Development Setup Guide](docs/SETUP.md)** - Complete setup from scratch
- **[Architecture Overview](docs/ARCHITECTURE.md)** - System design and components
- **[Protocol Specification](docs/PROTOCOL.md)** - Message format and contracts
- **[Roadmap](planning/ROADMAP.md)** - Phase breakdown and timeline
- **[Verify Foundation](scripts/test-foundation.sh)** - Run `bash scripts/test-foundation.sh`

## Core Value Proposition

- **Autonomous Orchestration:** Natural language requests become infrastructure changes
- **Full Auditability:** Git audit trail + PostgreSQL event log for every decision
- **Cost Aware:** Minimize external AI calls; local LLM + Claude fallback
- **Resource Aware:** Desktop agents report GPU/CPU availability; work queued intelligently
- **Human Approval:** Every significant action waits for human confirmation

## v1 Goals

Proof-of-concept validation using a Kuma Uptime deployment use case:
1. User requests "Deploy Kuma Uptime to homelab and add existing portals to config"
2. System parses intent, discovers existing configs, presents execution plan
3. User approves; system executes via infrastructure agent
4. Ansible playbooks run with streamed output
5. Changes committed to git with full audit trail
6. State recorded in PostgreSQL with resource metrics

## Prerequisites

- **Python 3.11+**
- **Poetry** (https://python-poetry.org/)
- **Docker & Docker Compose**
- **Git** (for audit trails)

## Verification

After setup, verify everything is working:

```bash
bash scripts/test-foundation.sh
```

This script checks:
- System prerequisites (Python, Docker, Poetry)
- Project structure and dependencies
- Docker service health
- Database schema and sample data
- Protocol tests and code quality

## Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/yourusername/chiffon.git
cd chiffon
poetry install
```

### 2. Start Infrastructure Services

```bash
docker-compose up -d
```

Wait 30 seconds for services to become healthy:
```bash
docker-compose ps
```

All services should show status `Up (healthy)`.

### 3. Initialize Database

```bash
poetry run alembic upgrade head
```

### 4. Run Tests

```bash
poetry run pytest tests/ -v
```

### 5. Start Orchestrator

For development with hot reload:

```bash
poetry run uvicorn src.orchestrator.main:app --reload
```

Visit health check: `http://localhost:8000/health`

## Project Structure

```
chiffon/
├── src/
│   ├── orchestrator/          # Main orchestration service
│   │   └── main.py            # FastAPI app entry point
│   ├── agents/                # Agent implementations (Phase 3+)
│   └── common/
│       ├── config.py          # Configuration from .env
│       ├── database.py        # SQLAlchemy setup
│       └── models.py          # ORM models (Task, ExecutionLog)
├── tests/                     # Test suite
├── migrations/                # Alembic database migrations
├── docs/                      # Documentation
├── docker-compose.yml         # Service definitions
├── Dockerfile                 # Orchestrator container
├── pyproject.toml             # Python dependencies (Poetry)
└── README.md                  # This file
```

## Development Tools

### Code Quality

Format code with Black:
```bash
poetry run black src/ tests/
```

Check style with Ruff:
```bash
poetry run ruff check src/ tests/ --fix
```

Type checking with mypy:
```bash
poetry run mypy src/
```

### Services

- **PostgreSQL (5432):** Task state, execution logs, audit trail
- **RabbitMQ (5672, 15672 UI):** Message bus for agent orchestration
- **Ollama (11434):** Local LLM for routine planning (llama2, mistral, etc.)
- **LiteLLM (8001):** LLM proxy (Claude, OpenAI, local models)

View RabbitMQ Management UI: `http://localhost:15672` (guest/guest)

### Stopping Services

```bash
docker-compose down
```

To wipe data:
```bash
docker-compose down -v
```

## Deploying llama.cpp via GHCR + Ansible

We now build the GPU-enabled llama.cpp image ahead of time and host it on GitHub Container Registry so the Windows host only needs to pull and run it.

1. **Publish the image** by pushing to `main` or `phase/01-foundation`. The [Publish llama.cpp image](.github/workflows/publish-llamacpp.yml) workflow builds `Dockerfile.llamacpp` and pushes `ghcr.io/<your-org>/chiffon-llamacpp:latest` plus a SHA-tagged image.
2. **Keep your inventory in `homelab_infra`** (or another infra repo) so host records, SSH keys, and connection details stay separate. Point to that inventory when running Ansible, e.g.:

   ```bash
   ansible-playbook \
     -i ~/Projects/homelab_infra/ansible/inventory.ini \
     ansible/deploy-llamacpp.yml \
     -e ghcr_owner=HavartiBard \
     -e ghcr_tag=latest
   ```

   The playbook copies a GHCR-aware `docker-compose.yml`, pulls the image, and starts the GPU service; its defaults assume `ghcr_owner` = repo owner but you can override `ghcr_tag` to a release SHA.
3. **Ensure the Windows host can reach GHCR** by logging in once inside WSL (`docker login ghcr.io`). Store the PAT that has `read:packages` so subsequent pulls run without extra steps.

This approach keeps deployments repeatable, avoids compiling `llama.cpp` on the Windows machine, and lets you roll forward by tagging a new GHCR image plus rerunning the playbook.

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
# Edit .env with your API keys and credentials
```

Key variables:
- `ANTHROPIC_API_KEY` - Claude API access (optional for dev)
- `DATABASE_URL` - PostgreSQL connection string
- `RABBITMQ_URL` - RabbitMQ connection string
- `LOG_LEVEL` - Python logging level (DEBUG, INFO, WARNING, ERROR)

## Architecture

### Orchestrator

Central service that:
- Parses user requests
- Plans infrastructure changes
- Dispatches work to agents
- Tracks execution state
- Logs all decisions

### Agents (v1 MVP)

- **Infrastructure Agent:** Wraps Ansible playbooks; executes infrastructure changes
- **Desktop Agents:** Report GPU/CPU metrics; execute local tasks

### State Model

- **PostgreSQL:** Real-time state (tasks, logs, metrics)
- **Git:** Immutable audit trail (commits for every decision)

## Performance Targets

- Request parse to approval UI: <5 seconds
- Task execution: Depends on infrastructure (Ansible timescale)
- Cost per task: <$0.50 external AI (via local LLM + Claude fallback)

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Foundation (Python, Docker, DB) | In Progress |
| 2 | Message Bus (RabbitMQ protocol) | Pending |
| 3 | Orchestrator Core (planning, dispatch) | Pending |
| 4 | Desktop Agent (resource awareness) | Pending |
| 5 | State & Audit (PostgreSQL, git) | Pending |
| 6 | Infrastructure Agent (Ansible) | Pending |
| 7 | User Interface (chat interface) | Pending |
| 8 | E2E Integration (Kuma validation) | Pending |

## Support

For issues, questions, or contributions:
- Open an issue on GitHub
- Check `/docs` for architecture deep-dives
- Review `/REQUIREMENTS.md` for v1 scope

---

**Chiffon v1:** December 2025 - January 2026
Built with intention, audited with rigor, automated with care.
