# Chiffon Development Setup Guide

This guide covers local development setup for Chiffon, including obtaining API keys and running LiteLLM locally.

## Prerequisites

- Docker and Docker Compose installed
- Python 3.11+
- Poetry (Python dependency manager)
- Git

## Step 1: Clone and Install Dependencies

```bash
git clone <repository>
cd chiffon

# Install Python dependencies using Poetry
poetry install
```

## Step 2: Create Environment Variables

Copy the example environment file and configure API keys:

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

```env
# Anthropic Claude API (primary LLM)
ANTHROPIC_API_KEY=sk-ant-...  # https://console.anthropic.com/account/keys

# OpenAI GPT-4 (fallback LLM - optional for Phase 1)
OPENAI_API_KEY=sk-...  # https://platform.openai.com/account/api-keys

# LiteLLM master key (for local testing)
LITELLM_MASTER_KEY=dev-key
```

### Obtaining API Keys

#### Anthropic API Key (Required)

1. Go to https://console.anthropic.com/account/keys
2. Create a new API key
3. Copy the key and add to `.env` as `ANTHROPIC_API_KEY`

#### OpenAI API Key (Optional - for GPT-4 fallback)

1. Go to https://platform.openai.com/account/api-keys
2. Create a new API key
3. Copy the key and add to `.env` as `OPENAI_API_KEY`
4. Note: Not required for Phase 1 (Ollama provides free fallback)

## Step 3: Start Docker Services

Start all required services (PostgreSQL, RabbitMQ, Ollama, LiteLLM):

```bash
docker-compose up -d
```

Wait for services to be healthy (30-60 seconds):

```bash
docker-compose ps
# All services should show STATUS: Up
```

## Step 4: Verify Services

### Check LiteLLM Service

```bash
# Health check
curl http://localhost:8001/health

# Expected response:
# {"status":"ok"}
```

### Check Ollama Service

```bash
# Get available models
curl http://localhost:11434/api/tags

# Expected response (initially empty):
# {"models":[]}
```

### Pre-load Ollama Model

The first time you run Ollama, you need to pull a model. This takes 3-5 minutes and ~2GB disk space.

#### Option A: Using API (recommended)

```bash
# Pull neural-chat model (~4GB)
curl -s http://localhost:11434/api/pull -d '{"name":"neural-chat"}' | jq .

# Watch the download progress in the output
# When complete, you'll see: "status":"success"
```

#### Option B: Using Docker exec

```bash
docker exec agent-deploy-ollama ollama pull neural-chat
```

#### Option C: Manual CLI

```bash
# Enter Ollama container
docker exec -it agent-deploy-ollama bash

# Pull the model
ollama pull neural-chat

# Exit
exit
```

### Verify Ollama Model is Loaded

```bash
# Should show neural-chat in the list
curl http://localhost:11434/api/tags | jq '.models[].name'

# Expected output:
# "neural-chat:latest"
```

## Step 5: Test LiteLLM Locally

### Run Unit Tests

```bash
# Run all LiteLLM client tests (mocked, no external API calls)
poetry run pytest tests/test_litellm_client.py -v

# Expected: All 19 tests pass
```

### Test with Real LiteLLM Service (Optional)

Create a test script to verify end-to-end calling:

```python
# test_litellm_integration.py
from src.common.litellm_client import LiteLLMClient

client = LiteLLMClient(base_url="http://localhost:8001")

# Check health
print(f"LiteLLM health: {client.get_health()}")

# List available models
models = client.get_available_models()
print(f"Available models: {models}")

# Make a test call (will use Ollama if no API keys set)
messages = [{"role": "user", "content": "Say hello"}]
try:
    response = client.call_llm("ollama/neural-chat", messages)
    print(f"Response: {response['choices'][0]['message']['content']}")
except Exception as e:
    print(f"Error: {e}")
```

Run it:

```bash
poetry run python test_litellm_integration.py
```

## LiteLLM Fallback Chain

LiteLLM is configured with an intelligent fallback strategy:

1. **Primary (Claude):** `claude-opus-4.5`
   - Uses Anthropic API key from environment
   - Best for complex reasoning tasks
   - Monthly limit: $100 USD with 80% threshold

2. **Fallback 1 (GPT-4):** `gpt-4-turbo`
   - Uses OpenAI API key from environment
   - Better general-purpose model
   - Monthly limit: $50 USD with 80% threshold
   - Optional for Phase 1

3. **Fallback 2 (Ollama):** `ollama/neural-chat`
   - Local, zero-cost model
   - Always available (no API key needed)
   - Fast response times
   - Lower accuracy (trade-off for cost optimization)

**Routing Strategy:** When Claude API quota hits 80%, requests automatically fallback to GPT-4. When both external APIs are exhausted or timeout, Ollama is used.

## Configuration Files

### LiteLLM Config

Location: `config/litellm-config.json`

Key settings:
- `fallback_strategy`: Chain of models to try in order
- `quota_limits`: Monthly spending limits for each API
- `cache_config`: Response caching to reduce API calls
- `api_timeout`: 30 seconds per request

### Docker Compose

Location: `docker-compose.yml`

Services configured:
- **postgres** (5432): PostgreSQL database for state and audit logs
- **rabbitmq** (5672): Message queue for agent communication
- **ollama** (11434): Local LLM provider
- **litellm** (8001): LLM proxy with fallback chain
- **orchestrator** (8000): Main orchestration service

## Troubleshooting

### LiteLLM Service Won't Start

```bash
# Check logs
docker-compose logs litellm

# Common issues:
# - Config file not found: Check config/litellm-config.json exists
# - Port already in use: Kill process on 8001 or change port mapping
# - API key missing: Not required for Ollama-only testing
```

### Ollama Model Won't Download

```bash
# Check Ollama logs
docker-compose logs ollama

# Verify disk space (needs ~2GB for neural-chat)
df -h

# Restart Ollama
docker-compose restart ollama

# Try pulling a smaller model
curl -s http://localhost:11434/api/pull -d '{"name":"orca-mini"}'
```

### Tests Fail

```bash
# Clear cache and reinstall
rm -rf .pytest_cache .venv
poetry install

# Run tests again
poetry run pytest tests/ -v
```

## Next Steps

1. **Phase 2: Message Bus** — RabbitMQ topology for agent communication
2. **Phase 3: Orchestrator Core** — Planning and task dispatch logic
3. **Phase 4: Desktop Agent** — Resource-aware agent for Ansible integration

## Useful Commands

```bash
# Start all services in background
docker-compose up -d

# Stop all services
docker-compose down

# View service logs
docker-compose logs -f <service-name>

# Run tests
poetry run pytest tests/ -v

# Format code
poetry run black src/ tests/

# Lint code
poetry run ruff check src/ tests/

# Type check
poetry run mypy src/
```

## Support

For issues or questions, refer to:
- Project README: `/README.md`
- Agent Protocol: `/docs/PROTOCOL.md`
- Issue tracker: Project repository

---

**Last Updated:** 2026-01-19
**Status:** Active (Phase 1: Foundation)
