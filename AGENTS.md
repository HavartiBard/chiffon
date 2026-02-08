# Repository Guidelines

## Session Start

When beginning a new session without a specific task, offer to review open Gitea issues:

```bash
curl -s "https://code.klsll.com/api/v1/repos/HavartiBard/chiffon/issues?state=open&type=issues&limit=20" \
  -H "Authorization: token $GITEA_TOKEN" | jq '.[] | {number, title, labels: [.labels[].name]}'
```

Present the issues as a numbered list and ask which one to work on. If the user already has a task, skip this.

## Project Structure & Module Organization
- `src/` hosts the FastAPI orchestrator (`src/orchestrator/main.py`), agents, and shared helpers (`common/`, `config.py`, `database.py`, `models.py`).
- `tests/` mirrors `src/` modules and keeps end-to-end checks; add new suites here before expanding coverage.
- `docs/`, `scripts/`, and `migrations/` hold design references, automation helpers, and Alembic state respectively; update docs when behavior changes.
- Docker assets (`Dockerfile*`, `docker-compose*.yml`) live at the repo root; `frontend/` contains any client dashboard work, while `config/` and `data/` store environment recipes and seeded fixtures.

## Build, Test, and Development Commands
- `poetry install`: resolve dependencies across the Python stack.
- `bash scripts/test-foundation.sh`: smoke-check prerequisites, Docker health, and basic protocol sanity.
- `docker-compose up -d && docker-compose ps`: spin up and verify services (PostgreSQL, RabbitMQ, Ollama, LiteLLM).
- `poetry run alembic upgrade head`: migrate the PostgreSQL schema before running the orchestrator.
- `poetry run pytest tests/ -v`: execute the Pytest suite under `tests/`; rerun before merging.
- `poetry run black src/ tests/`: auto-format Python sources.
- `poetry run ruff check src/ tests/ --fix`: lint the codebase and optionally fix violations.
- `poetry run mypy src/`: verify static typing contracts.
- `poetry run uvicorn src.orchestrator.main:app --reload`: start the orchestrator with hot reload for local work.
- `docker-compose down` (add `-v` to reset volumes): stop services and clean state.

## Coding Style & Naming Conventions
- Python uses 4-space indentation, Black formatting, and Ruff linting; keep imports grouped (stdlib, third-party, local) and alphabetized.
- Favor `snake_case` for functions/variables, `PascalCase` for classes/Enums, and `CAPITAL_SNAKE` for module-level constants.
- Use descriptive names for protocols and messages (`TaskPlan`, `ExecutionLogEntry`) and keep module filenames aligned with their main classes (e.g., `agents/infrastructure.py` for `InfrastructureAgent`).
- Document configuration with `.env.example` and prefer `config.settings` over hard-coded values; string or numerical env vars should be cast in a single place.

## Testing Guidelines
- Tests live under `tests/` with modules mirroring production packages; name them `test_*.py` and keep fixtures in `tests/fixtures/` when possible.
- Rely on Pytest; use `pytest.mark` sparingly and focus on clear arrange-act-assert blocks.
- Run `poetry run pytest tests/ -v` after changes and include failing test reproduction steps in PRs.
- Aim for meaningful coverage around orchestrator flows, agent dispatch, and database models; record regressions in `tests/` before touching `src/` code.

## Commit & Pull Request Guidelines
- Follow the conventional commit pattern (e.g., `fix(deploy): ensure CUDA build for llama.cpp`) as seen in recent history; scope should be a subsystem and the subject short, present tense.
- Pull requests need a clear summary, linked issue(s) when available, and verification steps (e.g., `poetry run pytest tests/ -v`, `bash scripts/test-foundation.sh`).
- Mention any manual test results (Docker checks, migrations applied) in the PR description and upload screenshots only if UI changes occur.
- Update docs (`docs/`, `README.md`, or this AGENTS.md) whenever behavior, setup, or architecture shifts.

## Security & Configuration Tips
- Copy `.env.example` to `.env`, keep secret keys out of Git, and only share configurations over secure channels.
- Trust local LLM endpoints (`Ollama`, `LiteLLM`) by default; ensure Docker secrets or mounted volumes are read-only when possible.
