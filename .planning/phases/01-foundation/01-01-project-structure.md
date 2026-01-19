---
phase: 01-foundation
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - .gitignore
  - .env.example
  - Dockerfile
  - docker-compose.yml
  - src/orchestrator/__init__.py
  - src/orchestrator/main.py
  - src/common/__init__.py
  - src/common/config.py
  - tests/__init__.py
  - tests/conftest.py
  - .github/workflows/ci.yml
  - README.md
autonomous: true
user_setup: []

must_haves:
  truths:
    - "User can clone repo and see complete project structure (src/, tests/, migrations/, docs/)"
    - "User can run 'poetry install' without errors (dependencies resolved)"
    - "User can run 'docker-compose up' and see all services start healthily"
    - "User can see code quality tools configured (black, ruff) and passing"
  artifacts:
    - path: "pyproject.toml"
      provides: "Dependency management, Poetry config, tool settings"
      contains: ["fastapi", "sqlalchemy", "pydantic", "pika", "alembic", "black", "ruff", "pytest"]
    - path: "docker-compose.yml"
      provides: "Local development stack definition"
      exports: ["postgres:15", "rabbitmq", "ollama", "litellm"]
    - path: ".gitignore"
      provides: "Excludes .env, __pycache__, venv, test artifacts"
    - path: "src/orchestrator/main.py"
      provides: "FastAPI application entry point"
      min_lines: 25
    - path: "src/common/config.py"
      provides: "Configuration loading from .env"
      contains: ["pydantic BaseSettings", "DATABASE_URL", "RABBITMQ_URL"]
  key_links:
    - from: "pyproject.toml"
      to: "docker-compose.yml"
      via: "Python 3.11+ required by both"
      pattern: "python"
    - from: ".env.example"
      to: "src/common/config.py"
      via: "Config reads from environment"
      pattern: "ANTHROPIC_API_KEY|OPENAI_API_KEY"
    - from: "src/orchestrator/main.py"
      to: "docker-compose.yml"
      via: "App starts after services healthy"
      pattern: "depends_on"
---

## Plan: Project Scaffolding, Python Setup, Docker Environment

**Goal:** Complete project structure, Poetry dependencies, Docker services, and development environment ready for core implementation.

**Deliverables:**
- Python project structure (src/, tests/, migrations/, docs/)
- Poetry pyproject.toml with all Phase 1 + Phase 2 dependencies
- Docker Compose with PostgreSQL, RabbitMQ, Ollama, LiteLLM services
- Development environment: black, ruff, pytest configured
- Sample FastAPI application entry point (empty routes, ready for Phase 2+)

**Success Criteria:**
- `poetry install` completes without errors
- `docker-compose up -d` starts all services with health checks passing
- `poetry run black --check src/` and `poetry run ruff check src/` pass
- `poetry run pytest tests/` runs (even if tests are minimal)
- No secrets leaked in .gitignore/.env.example

### Tasks

<task type="auto">
  <name>Task 1: Create project structure, Poetry config, and development tools</name>
  <files>
    pyproject.toml
    .gitignore
    .env.example
    src/orchestrator/__init__.py
    src/orchestrator/main.py
    src/common/__init__.py
    src/common/config.py
    src/agents/__init__.py
    tests/__init__.py
    tests/conftest.py
  </files>
  <action>
    Create the directory structure and foundational files:

    1. **pyproject.toml** - Python package configuration with Poetry:
       - Python 3.11+ requirement
       - Core dependencies: fastapi, uvicorn, sqlalchemy, alembic, pydantic, pika
       - LLM integration: litellm, python-dotenv
       - Dev dependencies: pytest, black, ruff, mypy
       - Tool configuration: [tool.black], [tool.ruff], [tool.pytest.ini_options]
       - Include script entry point: `orchestrator = "src.orchestrator.main:app"`

    2. **.gitignore** - Exclude all sensitive/runtime files:
       - .env (but not .env.example)
       - __pycache__/, *.pyc, .pytest_cache/, .mypy_cache/
       - venv/, .venv/
       - *.log, logs/
       - .DS_Store
       - poetry.lock (commit this)

    3. **.env.example** - Template for environment variables (NO VALUES):
       - DATABASE_URL=postgresql://user:password@localhost:5432/agent_deploy
       - RABBITMQ_URL=amqp://guest:guest@localhost:5672/
       - ANTHROPIC_API_KEY=
       - OPENAI_API_KEY=
       - LITELLM_MASTER_KEY=
       - LOG_LEVEL=INFO

    4. **src/orchestrator/main.py** - FastAPI application skeleton:
       - Minimal FastAPI app with lifespan context manager
       - Health check endpoint: GET /health
       - Ready for routes in Phase 2+
       - Environment config loaded via Config class
       - Structured logging setup using Python logging

    5. **src/common/config.py** - Pydantic settings:
       - BaseSettings model with all required environment variables
       - DEFAULT values for development (e.g., DATABASE_URL defaults to local)
       - @validator for critical URLs (DATABASE_URL must start with postgresql://)
       - Docstrings explaining each setting

    6. **src/common/__init__.py, src/orchestrator/__init__.py, src/agents/__init__.py** - Empty init files

    7. **tests/conftest.py** - pytest fixtures (minimal):
       - @pytest.fixture for test database (sqlite in-memory)
       - @pytest.fixture for async client if using FastAPI async
       - Setup/teardown for any shared test resources

    8. **tests/__init__.py** - Empty init file

    Use Poetry locking for exact versions (not just ~= ranges, except major packages).
  </action>
  <verify>
    - `poetry lock --no-update` generates poetry.lock without errors
    - `poetry env info` shows Python 3.11+
    - `grep -E "name = \"orchestrator\"|entry-points" pyproject.toml` shows script entry
    - `.gitignore` contains `.env` but `.env.example` does not
    - `python -m py_compile src/orchestrator/main.py` succeeds (syntax valid)
  </verify>
  <done>
    - pyproject.toml defined with all dependencies for Phase 1 + 2
    - Directory structure created and importable (can `from src.orchestrator import app`)
    - Config system ready to load environment variables
    - Empty orchestrator FastAPI app runs on startup
  </done>
</task>

<task type="auto">
  <name>Task 2: Create Docker Compose stack with PostgreSQL, RabbitMQ, Ollama, LiteLLM</name>
  <files>
    docker-compose.yml
    Dockerfile
  </files>
  <action>
    Create containerized local development environment:

    1. **docker-compose.yml** - Multi-service definition:
       - Service: postgres:15-alpine
         - Environment: POSTGRES_USER=agent, POSTGRES_PASSWORD=password, POSTGRES_DB=agent_deploy
         - Volumes: ./data/postgres:/var/lib/postgresql/data (persistence)
         - Port: 5432 exposed locally
         - Health check: pg_isready every 10s

       - Service: rabbitmq:3.12-management-alpine
         - Default credentials: guest/guest (for dev only)
         - Plugins: rabbitmq_management enabled
         - Port: 5672 (AMQP), 15672 (Management UI) exposed
         - Health check: curl localhost:15672 every 10s

       - Service: ollama:latest
         - Pull ollama/ollama image
         - Port: 11434 exposed
         - Volume: /root/.ollama (model cache)
         - Health check: curl localhost:11434/api/tags or similar
         - Note: First run downloads base model (~3-5 min), document this

       - Service: litellm:latest or custom Dockerfile
         - Build from custom Dockerfile (FastAPI wrapper)
         - Port: 8001 exposed
         - Environment: Pass ANTHROPIC_API_KEY, OPENAI_API_KEY from .env
         - Volume: ./config/litellm-config.json:/app/config.json
         - Health check: curl localhost:8001/health

       - Service: orchestrator (optional for Phase 1, but scaffold for Phase 2)
         - Build: ./Dockerfile
         - Depends on: postgres, rabbitmq, litellm (not critical in Phase 1)
         - Port: 8000 exposed (will be active in Phase 2)
         - Environment: Pass DATABASE_URL, RABBITMQ_URL from .env
         - For Phase 1, orchestrator runs locally in dev (not in compose)

       - Networks: default network, all services can communicate by service name (postgres:5432, rabbitmq:5672, etc.)

    2. **Dockerfile** - Python application container:
       - Base: python:3.11-slim
       - Working directory: /app
       - Copy pyproject.toml, poetry.lock, install dependencies
       - Copy src/ and tests/
       - CMD: ["uvicorn", "src.orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
       - No secrets baked in (uses env vars)

    Ensure all services are resilient to startup order (use depends_on with condition: service_healthy).
  </action>
  <verify>
    - `docker-compose config` shows valid YAML
    - `docker-compose pull` downloads all images without errors
    - `docker-compose up -d` starts services
    - Wait 30s, then `docker-compose ps` shows all services UP (green)
    - `docker exec agent-deploy-postgres-1 psql -U agent -d agent_deploy -c "SELECT 1"` returns success
    - `docker exec agent-deploy-rabbitmq-1 rabbitmq-diagnostics -q status` shows running
    - `curl localhost:15672` (RabbitMQ UI) responds 200
    - `curl localhost:11434/api/tags` (Ollama API) responds JSON
    - `docker-compose logs litellm | grep "Uvicorn running"` or similar (service started)
    - `docker-compose down` stops all containers without errors
  </verify>
  <done>
    - docker-compose.yml defines all Phase 1 foundation services
    - Services start healthily with correct networking
    - PostgreSQL, RabbitMQ, Ollama, LiteLLM accessible from localhost
    - Environment variables passed via .env without hardcoding secrets
  </done>
</task>

<task type="auto">
  <name>Task 3: Set up code quality tools and CI/CD placeholder</name>
  <files>
    .github/workflows/ci.yml
    README.md
  </files>
  <action>
    Configure development quality gates and documentation:

    1. **.github/workflows/ci.yml** - GitHub Actions CI pipeline (placeholder for Phase 1, will expand in later phases):
       - Trigger: on push to main, pull_request
       - Jobs:
         - Lint: `poetry run black --check src/ tests/` and `poetry run ruff check src/ tests/`
         - Test: `poetry run pytest tests/` (collect coverage)
         - Build: `docker build -t agent-deploy:latest .` (verify Dockerfile valid)
       - Python 3.11 runner
       - Install Poetry, run above commands
       - No deployment in Phase 1 (but scaffold for Phase 2)

    2. **README.md** - Project overview and quick start:
       - Title, description, core value proposition
       - Prerequisites (Python 3.11+, Docker, Poetry)
       - Quick start:
         ```
         poetry install
         docker-compose up -d
         poetry run alembic upgrade head
         poetry run pytest
         poetry run uvicorn src.orchestrator.main:app --reload
         ```
       - Project structure explanation
       - Contact/support info (if applicable)
       - Link to SETUP.md (to be created in next plan)
  </action>
  <verify>
    - `poetry run black --check src/` passes (or reports files to format)
    - `poetry run ruff check src/` passes
    - GitHub Actions workflow validates as YAML (if repo is on GitHub)
    - README.md is readable and contains all quick-start steps
  </verify>
  <done>
    - Code quality checks automated (black, ruff)
    - CI/CD pipeline scaffolded (GitHub Actions)
    - Documentation for quick start complete
  </done>
</task>

</tasks>

<verification>
After all tasks complete:
1. Clone repo from scratch in temp directory
2. Run `poetry install` — should succeed
3. Run `docker-compose up -d` and wait 30s
4. Verify all services healthy: `docker-compose ps`
5. Run `poetry run pytest tests/conftest.py -v` — should collect tests
6. Run `poetry run black --check src/ && poetry run ruff check src/` — should pass
7. Verify .gitignore excludes .env but not .env.example
8. Verify FastAPI app starts: `poetry run uvicorn src.orchestrator.main:app --reload` responds to GET /health
</verification>

<success_criteria>
- Project structure established (src/, tests/, migrations/, docs/ directories exist)
- Poetry environment resolves all dependencies (no conflicts)
- Docker Compose brings up all foundation services healthy
- Code quality tools configured and passing
- FastAPI skeleton ready for Phase 2 routes
- All infrastructure IaC committed to git (Dockerfile, docker-compose.yml, pyproject.toml)
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-01-SUMMARY.md` with:
- Services running (postgres, rabbitmq, ollama, litellm confirmed healthy)
- Dependencies locked (poetry.lock committed)
- Code quality passing (black, ruff output)
- First health check successful (`poetry run pytest` collection succeeds)
</output>
