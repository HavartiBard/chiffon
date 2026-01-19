---
phase: 01-foundation
plan: 05
type: execute
wave: 3
depends_on: ["01-01", "01-02", "01-03", "01-04"]
files_modified:
  - docs/SETUP.md
  - docs/ARCHITECTURE.md
  - README.md
  - scripts/test-foundation.sh
autonomous: true
user_setup: []

must_haves:
  truths:
    - "User can follow SETUP.md from scratch and have working local environment"
    - "ARCHITECTURE.md explains project structure and Phase 1 foundation"
    - "Test script verifies all Phase 1 success criteria in one command"
    - "All Phase 1 deliverables documented and ready for Phase 2"
  artifacts:
    - path: "docs/SETUP.md"
      provides: "Complete setup guide for new developer"
      contains: ["Prerequisites", "Installation", "API Keys", "Quick Start", "Troubleshooting"]
    - path: "docs/ARCHITECTURE.md"
      provides: "High-level architecture and component overview"
      contains: ["PostgreSQL", "RabbitMQ", "Orchestrator", "Agents", "Message Protocol"]
    - path: "scripts/test-foundation.sh"
      provides: "Automated verification of Phase 1 foundation"
      exports: ["health checks", "schema verification", "service connectivity"]
  key_links:
    - from: "docs/SETUP.md"
      to: ".env.example"
      via: "Setup guide explains how to populate .env"
      pattern: "ANTHROPIC_API_KEY"
    - from: "docs/ARCHITECTURE.md"
      to: "src/common/protocol.py"
      via: "Architecture explains protocol design decisions"
      pattern: "JSON envelope"
    - from: "scripts/test-foundation.sh"
      to: "docker-compose.yml"
      via: "Test script verifies services via compose"
      pattern: "docker-compose"
---

## Plan: Documentation Completion, Setup Guide, Phase 1 Verification Script

**Goal:** Complete all Phase 1 documentation. Create setup guide for new developers. Build automated verification script that confirms all success criteria.

**Deliverables:**
- docs/SETUP.md: Complete setup from scratch to working environment
- docs/ARCHITECTURE.md: High-level component overview
- scripts/test-foundation.sh: Automated Phase 1 verification
- Updated README.md with links to docs

**Success Criteria:**
- `bash scripts/test-foundation.sh` passes all checks
- New developer can follow SETUP.md without external help
- ARCHITECTURE.md explains why each component exists
- All Phase 1 success criteria verifiable via test script

### Tasks

<task type="auto">
  <name>Task 1: Write comprehensive SETUP.md and ARCHITECTURE.md</name>
  <files>
    docs/SETUP.md
    docs/ARCHITECTURE.md
  </files>
  <action>
    Create developer onboarding documentation:

    1. **docs/SETUP.md** - Setup guide for new developers:
       - Title: "Development Environment Setup"
       - Prerequisites section:
         - Python 3.11+
         - Docker + Docker Compose
         - Git
         - (Optional) GitHub CLI for local testing

       - Installation section:
         - Clone repo: `git clone https://github.com/...agent-deploy.git`
         - Install Python deps: `poetry install`
         - Create .env from .env.example: `cp .env.example .env`
         - Explain each env var: DATABASE_URL, RABBITMQ_URL, ANTHROPIC_API_KEY, OPENAI_API_KEY

       - API Keys section:
         - **Anthropic (Claude)**:
           - Visit https://console.anthropic.com/account/keys
           - Create new key, copy to ANTHROPIC_API_KEY in .env
           - Note: Phase 1 works without this (will use Ollama fallback)
         - **OpenAI (GPT-4)** [optional]:
           - Visit https://platform.openai.com/account/api-keys
           - Copy to OPENAI_API_KEY in .env
           - Not required for Phase 1, optional for fallback testing
         - Emphasize: Never commit .env to git

       - Docker Services section:
         - Start services: `docker-compose up -d`
         - Wait 30s for startup
         - Verify health: `docker-compose ps` (all services UP)
         - Check services individually:
           - PostgreSQL: `docker-compose exec postgres psql -U agent -d agent_deploy -c "SELECT 1"`
           - RabbitMQ: `curl http://localhost:15672/api/overview (admin UI at localhost:15672)`
           - Ollama: `curl http://localhost:11434/api/tags`
           - LiteLLM: `curl http://localhost:8001/health`
         - Note: Ollama first pull takes 3-5 min

       - Database Setup section:
         - Run migrations: `poetry run alembic upgrade head`
         - Load sample data: `poetry run python scripts/seed_sample_data.py`
         - Verify: `docker-compose exec postgres psql -U agent -d agent_deploy -c "SELECT COUNT(*) FROM tasks"`

       - Quick Start section:
         - Run tests: `poetry run pytest`
         - Code formatting: `poetry run black src/ tests/`
         - Linting: `poetry run ruff check src/ tests/`
         - Start orchestrator (Phase 2): `poetry run uvicorn src.orchestrator.main:app --reload`
         - Visit API docs: http://localhost:8000/docs (Swagger UI)

       - Troubleshooting section:
         - Port already in use: Identify process on port, change docker-compose.yml or stop process
         - PostgreSQL connection error: Check POSTGRES_PASSWORD in docker-compose.yml matches DATABASE_URL in .env
         - Ollama model not loading: Run `docker exec agent-deploy-ollama-1 ollama pull neural-chat` manually
         - LiteLLM API key errors: Verify ANTHROPIC_API_KEY is set (or remove for Ollama-only mode)

    2. **docs/ARCHITECTURE.md** - Architecture overview:
       - Title: "Agent-Deploy Architecture"
       - High-level diagram (ASCII or text description):
         ```
         User/Chat Interface
              ↓
         Orchestrator Service (FastAPI)
              ↓
         RabbitMQ Message Bus
          ↙     ↓     ↘
         Infra  Desktop  Code
         Agent  Agent    Agent
              ↓
         External Services (Ansible, GPU, etc.)
              ↓
         PostgreSQL (State + Audit)
         ```

       - Components section:
         - **Orchestrator (src/orchestrator/)**: Central service that receives requests, plans work, routes to agents
           - FastAPI service, runs locally in dev (container in prod)
           - Phase 2: adds planning + dispatch logic
           - Phase 3+: orchestrates multi-agent workflows

         - **RabbitMQ (docker-compose service)**: Message broker
           - Enables loose coupling between orchestrator and agents
           - Agents connect on startup, listen for work
           - Agents send status updates back via MQ
           - Survives service restarts (durable queues)

         - **PostgreSQL (docker-compose service)**: Operational state store
           - tasks table: what was requested, current status, outcome
           - execution_logs table: step-by-step execution history
           - Queried for post-mortem analysis, audit trails
           - Git holds historical archive

         - **LiteLLM (docker-compose service)**: LLM proxy
           - Vendor-agnostic interface to AI providers
           - Routes requests through fallback chain: Claude → GPT-4 → Ollama
           - Separates LLM choice from application code
           - Cost tracking via logs (Phase 2: integrate with PostgreSQL)

         - **Ollama (docker-compose service)**: Local LLM fallback
           - Zero-cost inference for routine planning
           - neural-chat or similar model
           - Used when external API quota exhausted or offline

         - **Protocol (src/common/protocol.py)**: Message format
           - JSON envelope with required fields (message_id, trace_id, request_id)
           - Message types: work_request, work_status, work_result, error
           - Error codes (5001-5999) for structured error handling
           - Enables version negotiation for v2 compatibility

       - Data Flow section:
         - Request enters orchestrator (natural language)
         - Orchestrator plans work (uses LiteLLM if needed)
         - Orchestrator sends work_request via RabbitMQ
         - Agent receives work_request, executes
         - Agent sends work_status updates during execution
         - Agent sends work_result when done
         - Orchestrator records in PostgreSQL + commits to git
         - User can audit via PostgreSQL queries or git log

       - Why this architecture section:
         - Loose coupling (MQ): agents can scale, restart independently
         - PostgreSQL for queries: faster than git log for analysis
         - Protocol versioning: enables v2 agents to coexist with v1
         - LiteLLM abstraction: easy to swap AI providers later
         - Git audit trail: immutable record of decisions + code

       - Technology choices section:
         - Why Python: Compatible with Ansible, GSD, existing tools
         - Why RabbitMQ: Mature, supports HA, durable queues
         - Why PostgreSQL: Strong queries for post-mortem, full ACID
         - Why FastAPI: Modern async Python, auto-generates OpenAPI docs
         - Why LiteLLM: Multi-provider support without vendor lock-in

  </action>
  <verify>
    - `wc -l docs/SETUP.md docs/ARCHITECTURE.md` shows both are substantial (>100 lines each)
    - `grep -i "prerequisite\|installation\|docker\|postgres\|api key" docs/SETUP.md` confirms key sections
    - `grep -i "orchestrator\|rabbitmq\|postgresql\|litellm\|protocol\|data flow" docs/ARCHITECTURE.md` confirms components
    - SETUP.md contains command examples (can copy/paste)
    - ARCHITECTURE.md contains ASCII diagram or clear text description
  </verify>
  <done>
    - SETUP.md complete with step-by-step instructions
    - ARCHITECTURE.md explains design decisions
    - Both documents cross-referenced
    - Ready for new developer onboarding
  </done>
</task>

<task type="auto">
  <name>Task 2: Create automated Phase 1 verification script</name>
  <files>
    scripts/test-foundation.sh
  </files>
  <action>
    Create bash script to verify all Phase 1 success criteria:

    1. **scripts/test-foundation.sh** - Comprehensive foundation test:
       - Shebang: #!/bin/bash -e (exit on error)
       - Set -u (error on undefined vars), set -o pipefail
       - Colors for output (green for pass, red for fail)

       - Functions:
         - check_command(cmd_name): Verify command available
         - check_service(service_name): Check docker-compose service running
         - check_port(port, expected_response): Verify port accessible
         - verify_file(filepath): Check file exists
         - run_test(test_name, command): Run test and report result

       - Main script flow:
         1. Print header: "Agent-Deploy Phase 1 Foundation Verification"
         2. Check prerequisites: Python 3.11+, Docker, docker-compose, Poetry
         3. Check environment: .env exists, key vars set
         4. Check project structure: src/, tests/, migrations/, docs/ exist
         5. Check dependencies: `poetry check` succeeds
         6. Check Docker services: `docker-compose ps` shows all UP
         7. Check PostgreSQL:
            - Connect and query: `docker-compose exec postgres psql -U agent -d agent_deploy -c "SELECT COUNT(*) FROM tasks"`
            - Run migrations: `poetry run alembic current` shows "001_initial_schema"
            - Query sample data: `SELECT COUNT(*) FROM tasks` > 0
         8. Check RabbitMQ:
            - Connect: `curl -s http://localhost:15672/api/overview`
         9. Check Ollama:
            - Endpoint: `curl -s http://localhost:11434/api/tags`
         10. Check LiteLLM:
            - Health: `curl -s http://localhost:8001/health`
            - Config: `cat config/litellm-config.json | jq -e '.litellm.fallback_strategy' > /dev/null`
         11. Check Python modules:
            - Imports: `python -c "from src.common.models import Task; from src.common.protocol import MessageEnvelope; print('OK')"`
         12. Run unit tests: `poetry run pytest tests/test_protocol_contract.py -v`
         13. Check code quality:
            - Black: `poetry run black --check src/ tests/` or report files to format
            - Ruff: `poetry run ruff check src/ tests/`
         14. Print summary: "✓ X passed, ✗ Y failed"

       - Error handling:
         - On failure, print helpful message (e.g., "PostgreSQL not responding. Run: docker-compose up -d")
         - Collect all failures before exiting (don't stop on first error)
         - Return exit code > 0 if any check failed

       - Usage: bash scripts/test-foundation.sh (no args needed)

  </action>
  <verify>
    - `bash scripts/test-foundation.sh` runs successfully (or with known failures if services not running)
    - Script has executable bit: `ls -la scripts/test-foundation.sh | grep -E "^-.*x"`
    - Script provides useful output for debugging
    - Can identify which checks passed/failed
  </verify>
  <done>
    - Verification script created and tested
    - Can be run to confirm Phase 1 foundation ready
    - Useful for CI/CD in Phase 2+
  </done>
</task>

<task type="auto">
  <name>Task 3: Update README.md and finalize documentation</name>
  <files>
    README.md
  </files>
  <action>
    Update main README with links to documentation:

    1. **README.md** updates:
       - Ensure title and description clear
       - Add "Quick Links" section:
         - Development Setup: [SETUP.md](docs/SETUP.md)
         - Architecture Overview: [ARCHITECTURE.md](docs/ARCHITECTURE.md)
         - Protocol Specification: [PROTOCOL.md](docs/PROTOCOL.md)
         - Roadmap: [ROADMAP.md](.planning/ROADMAP.md)
       - Add "Verification" section:
         - "Run `bash scripts/test-foundation.sh` to verify Phase 1 foundation"
       - Project structure section (brief overview)
       - Contribution guidelines (if desired)
       - License (if applicable)

    Ensure README is easy to scan and directs readers to detailed docs.
  </action>
  <verify>
    - README.md contains links to key docs (SETUP, ARCHITECTURE, PROTOCOL)
    - README mentions test-foundation.sh script
    - README is readable and scannable (headings, bullet points)
  </verify>
  <done>
    - README updated with documentation links
    - Easy for new developers to find setup instructions
    - Phase 1 documentation complete
  </done>
</task>

</tasks>

<verification>
After all tasks complete:
1. bash scripts/test-foundation.sh — all checks pass or report specific failures
2. SETUP.md readable and contains all setup steps
3. ARCHITECTURE.md explains design decisions
4. README.md has quick links to documentation
5. New developer can follow SETUP.md and reach working environment
</verification>

<success_criteria>
- All Phase 1 documentation complete
- SETUP.md enables new developer onboarding
- ARCHITECTURE.md explains design rationale
- Verification script automates Phase 1 health checks
- README links to all key documentation
- Phase 1 foundation ready for handoff to Phase 2
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-05-SUMMARY.md` with:
- Documentation complete: SETUP.md, ARCHITECTURE.md, PROTOCOL.md all verified
- Verification script passes all Phase 1 checks
- README updated with documentation links
- Phase 1 foundation complete and documented
</output>
