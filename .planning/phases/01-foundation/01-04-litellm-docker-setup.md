---
phase: 01-foundation
plan: 04
type: execute
wave: 2
depends_on: ["01-01"]
files_modified:
  - docker-compose.yml
  - config/litellm-config.json
  - src/common/litellm_client.py
  - docs/SETUP.md
  - .env.example
autonomous: false
user_setup:
  - service: anthropic
    why: "Claude API for LiteLLM primary model"
    env_vars:
      - name: ANTHROPIC_API_KEY
        source: "Anthropic console (https://console.anthropic.com/account/keys)"
  - service: openai
    why: "GPT-4 as fallback model"
    env_vars:
      - name: OPENAI_API_KEY
        source: "OpenAI console (https://platform.openai.com/account/api-keys) [optional for v1]"

must_haves:
  truths:
    - "LiteLLM service runs in Docker and is accessible at http://localhost:8001"
    - "Ollama local LLM runs in Docker with a model pre-loaded"
    - "LiteLLM configuration routes requests through fallback chain (Claude → GPT-4 → Ollama)"
    - "Python client can call LiteLLM endpoint and receive responses"
    - "SETUP.md documents how to obtain API keys and test LiteLLM locally"
  artifacts:
    - path: "config/litellm-config.json"
      provides: "LiteLLM routing config with fallback strategy"
      contains: ["litellm", "fallback_strategy", "quota_limits", "claude", "gpt-4", "ollama"]
    - path: "src/common/litellm_client.py"
      provides: "Python wrapper for LiteLLM endpoint"
      exports: ["LiteLLMClient", "call_llm"]
      min_lines: 50
    - path: "docs/SETUP.md"
      provides: "Developer setup guide with LiteLLM instructions"
      contains: ["poetry install", "docker-compose up", "API keys", "test LiteLLM"]
  key_links:
    - from: "docker-compose.yml"
      to: "config/litellm-config.json"
      via: "Docker volume mount for config"
      pattern: "volumes.*litellm-config"
    - from: "src/common/litellm_client.py"
      to: ".env.example"
      via: "Client reads API keys from environment"
      pattern: "ANTHROPIC_API_KEY"
    - from: "config/litellm-config.json"
      to: ".env.example"
      via: "Config includes fallback chain with API key placeholders"
      pattern: "api_keys"
---

## Plan: LiteLLM Service Setup, Local Ollama Integration, Client Wrapper

**Goal:** LiteLLM deployed as vendor-agnostic LLM proxy. Ollama fallback running locally. Python client wrapper ready for Phase 2 orchestrator to use.

**Deliverables:**
- LiteLLM Docker service with config.json fallback chain
- Ollama local LLM running with model pre-loaded
- Python LiteLLMClient for easy API calls
- SETUP.md documentation for getting API keys and testing
- Config supports Claude (primary) → GPT-4 (fallback) → Ollama (zero-cost)

**Success Criteria:**
- `curl http://localhost:8001/health` returns 200 OK
- `curl http://localhost:11434/api/tags` (Ollama) returns available models
- LiteLLMClient can make a test call and receive response
- SETUP.md includes step-by-step for obtaining Anthropic API key
- User can test LiteLLM locally without external AI (using Ollama)

### Tasks

<task type="auto">
  <name>Task 1: Configure LiteLLM service and add to docker-compose.yml</name>
  <files>
    docker-compose.yml
    config/litellm-config.json
  </files>
  <action>
    Set up LiteLLM as a FastAPI service in Docker:

    1. **Update docker-compose.yml** - Add LiteLLM service:
       - Service: litellm
       - Image: ghcr.io/berriai/litellm:latest (or build custom if needed)
       - Ports: 8001:8001 (expose to host for testing)
       - Environment:
         - LITELLM_LOG_LEVEL=INFO
         - DATABASE_TYPE=postgres (optional, for quota tracking in Phase 2)
         - Pass through: ANTHROPIC_API_KEY, OPENAI_API_KEY from .env
       - Volumes:
         - ./config/litellm-config.json:/app/config.json:ro (read-only)
       - Depends on: postgres, rabbitmq (soft dependency)
       - Health check: curl http://localhost:8001/health every 10s
       - Command: if using custom Dockerfile, else use default entrypoint

    2. **config/litellm-config.json** - LiteLLM configuration:
       - Structure:
         ```json
         {
           "litellm": {
             "default_model": "claude-opus-4.5",
             "fallback_strategy": [
               "claude-opus-4.5",
               "gpt-4-turbo",
               "ollama/neural-chat"
             ],
             "log_level": "INFO",
             "debug": false,
             "api_timeout": 30,
             "cache_config": {
               "enable_cache": true,
               "type": "in_memory",
               "ttl": 3600
             },
             "quota_limits": {
               "claude": {
                 "monthly_limit_usd": 100,
                 "fallback_after_80_percent": true,
                 "rpm_limit": 100
               },
               "gpt4": {
                 "monthly_limit_usd": 50,
                 "fallback_after_80_percent": true,
                 "rpm_limit": 50
               }
             },
             "api_keys": {
               "ANTHROPIC_API_KEY": "{{ env.ANTHROPIC_API_KEY }}",
               "OPENAI_API_KEY": "{{ env.OPENAI_API_KEY }}"
             },
             "allowed_models": [
               "claude-opus-4.5",
               "gpt-4-turbo",
               "ollama/neural-chat"
             ]
           },
           "router": {
             "strategy": "cost-based",
             "fallback_on_quota_error": true,
             "fallback_on_timeout": true
           }
         }
         ```

    3. Ensure .env file is passed to docker-compose for variable substitution:
       - `docker-compose.yml` uses: `env_file: .env`
       - Or inline: `environment: ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}`

    Note: LiteLLM config uses environment variable references like `{{ env.ANTHROPIC_API_KEY }}` that need to be substituted at runtime or via shell before passing to container.
  </action>
  <verify>
    - `grep -A 20 "service.*litellm\|service: litellm" docker-compose.yml` shows LiteLLM service defined
    - `docker-compose config | grep -A 20 litellm` shows resolved configuration
    - `python -c "import json; json.load(open('config/litellm-config.json'))"` validates JSON syntax
    - Config contains fallback_strategy with at least 3 models (claude, gpt-4, ollama)
  </verify>
  <done>
    - LiteLLM service added to docker-compose.yml
    - Configuration file with fallback chain ready
    - Environment variables passed through .env
    - Service will start when docker-compose up runs
  </done>
</task>

<task type="auto">
  <name>Task 2: Add Ollama local LLM to docker-compose.yml and pre-load model</name>
  <files>
    docker-compose.yml
  </files>
  <action>
    Set up Ollama as zero-cost fallback LLM:

    1. **Update docker-compose.yml** - Add Ollama service:
       - Service: ollama
       - Image: ollama/ollama:latest
       - Ports: 11434:11434 (expose API)
       - Environment:
         - OLLAMA_NUM_PARALLEL=1 (keep lightweight)
       - Volumes:
         - ./data/ollama:/root/.ollama (model cache and data)
       - Health check: curl http://localhost:11434/api/tags every 30s
       - No dependencies (can start independently)

    2. **Model pre-loading**:
       - First run will be slow (downloads model)
       - Document this in SETUP.md: "First docker-compose up takes 3-5 min for Ollama"
       - Optionally create init script: `scripts/init-ollama-model.sh`
         - After compose up, run: `docker exec agent-deploy-ollama-1 ollama pull neural-chat`
         - Or: `curl http://localhost:11434/api/pull -d '{"name":"neural-chat"}'` (alternative endpoint)
       - For Phase 1: manual pull is acceptable, document in SETUP.md

    3. Model choice:
       - Default: `neural-chat` or `mistral` (fast, lightweight, ~7B params)
       - Trade-off: Speed > Accuracy for local fallback (LiteLLM uses Claude by default anyway)
       - If system is fast enough, use `orca-mini` or `zephyr` for better quality
       - Document in SETUP.md which model is being used and why

    Keep Ollama separate from LiteLLM in compose (Ollama is accessed by LiteLLM via HTTP).
  </action>
  <verify>
    - `docker-compose config | grep -A 15 "service: ollama\|ollama:"` shows service defined
    - `grep "11434" docker-compose.yml` shows port exposed
    - `docker-compose up -d && sleep 60 && curl http://localhost:11434/api/tags` responds with models (empty list initially)
    - After model pull: `curl http://localhost:11434/api/tags` shows model in list
  </verify>
  <done>
    - Ollama service added to docker-compose.yml
    - Local LLM ready for fallback (zero-cost)
    - Model pre-loading documented for first setup
    - LiteLLM can route requests to Ollama when quota limits hit
  </done>
</task>

<task type="auto">
  <name>Task 3: Create LiteLLM Python client wrapper and test</name>
  <files>
    src/common/litellm_client.py
    tests/test_litellm_client.py
  </files>
  <action>
    Create Python wrapper for easy LiteLLM API calls:

    1. **src/common/litellm_client.py** - LiteLLM client class:
       - Import: requests, json, os
       - Class LiteLLMClient:
         - __init__(base_url="http://localhost:8001", timeout=30):
           - Store base_url, timeout
           - Load LITELLM_MASTER_KEY from env (optional)
         - call_llm(model: str, messages: list, temperature: float = 0.7) -> dict:
           - Endpoint: POST /chat/completions
           - Payload: {model, messages, temperature}
           - Headers: Authorization if LITELLM_MASTER_KEY set
           - Return: Response JSON (choices[0].message.content)
           - Raise: requests.RequestException on timeout/failure
         - get_available_models() -> list:
           - Endpoint: GET /models
           - Return: list of model names (claude-opus-4.5, gpt-4-turbo, ollama/neural-chat)
         - get_health() -> bool:
           - Endpoint: GET /health
           - Return: True if 200 OK, False otherwise

       - Module-level function call_llm(model, messages, temperature=0.7, base_url="http://localhost:8001") -> dict:
         - Convenience function wrapping LiteLLMClient for one-off calls
         - Returns response dict or raises exception

    2. **tests/test_litellm_client.py** - Unit tests (mocked):
       - Use pytest-mock or unittest.mock
       - Mock requests.post and requests.get
       - Test: test_call_llm_success
         - Mock successful response with message content
         - Assert call_llm returns expected content
       - Test: test_call_llm_timeout
         - Mock timeout exception
         - Assert raises RequestException
       - Test: test_get_models
         - Mock GET /models endpoint
         - Assert returns list with expected models
       - Test: test_get_health
         - Mock health check (200 OK)
         - Assert returns True

    Do NOT make real HTTP calls in tests (Phase 2 can do integration test).
  </action>
  <verify>
    - `python -c "from src.common.litellm_client import LiteLLMClient, call_llm; print('Import OK')"` succeeds
    - `poetry run pytest tests/test_litellm_client.py -v` runs and all tests pass
    - Mock tests don't require actual LiteLLM service running
  </verify>
  <done>
    - LiteLLMClient class ready for Phase 2 orchestrator
    - Module-level convenience function available
    - Unit tests pass (mocked)
    - Ready for integration with real LiteLLM service in Phase 2
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>
    - LiteLLM Docker service configured with fallback chain
    - Ollama local LLM running in Docker
    - Python client wrapper ready to use LiteLLM API
  </what-built>
  <how-to-verify>
    1. Start Docker services: `docker-compose up -d && sleep 30`
    2. Check services running: `docker-compose ps` — should show postgres, rabbitmq, ollama, litellm all UP
    3. Test LiteLLM health: `curl http://localhost:8001/health` — should return 200 OK
    4. Test Ollama: `curl http://localhost:11434/api/tags` — should return JSON with models
    5. Populate Ollama model (if first run): `curl -s http://localhost:11434/api/pull -d '{"name":"neural-chat"}' | jq .` (watch for progress)
    6. Run LiteLLM client test: `poetry run pytest tests/test_litellm_client.py -v` — should pass
    7. Optional: Make a real call to LiteLLM (requires ANTHROPIC_API_KEY in .env):
       - Create small test script calling call_llm("claude-opus-4.5", [{"role": "user", "content": "Say hello"}])
       - If API key present, should get response; if not, should fall back to Ollama
    8. Verify config: `cat config/litellm-config.json | jq '.litellm.fallback_strategy'` — should show claude, gpt-4, ollama
  </how-to-verify>
  <resume-signal>
    Type "approved" once you've verified:
    - LiteLLM service running and healthy
    - Ollama running and accessible
    - Local model available (or queued for pull)
    - Python client tests pass

    Or describe any issues encountered so we can fix them.
  </resume-signal>
</task>

</tasks>

<verification>
After all tasks complete and checkpoint approval:
1. LiteLLM service running at localhost:8001 and healthy
2. Ollama service running at localhost:11434 with neural-chat model
3. config/litellm-config.json defines fallback chain
4. Python client wrapper tested and working
5. Unit tests pass (mocked)
6. SETUP.md includes LiteLLM setup instructions
</verification>

<success_criteria>
- LiteLLM service deployed and accessible
- Ollama local LLM configured and ready
- Python client wrapper ready for Phase 2 orchestrator
- Fallback chain (Claude → GPT-4 → Ollama) configured
- Cost optimization: Can use Ollama (free) for routine planning, Claude when quota available
- SETUP.md documents API key setup and local testing
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-04-SUMMARY.md` with:
- LiteLLM service health check confirmed
- Ollama service running with model loaded
- Fallback chain verified (all 3 models accessible)
- Client wrapper tested and ready
- Cost tracking config ready (quota limits defined for Claude, GPT-4)
</output>
