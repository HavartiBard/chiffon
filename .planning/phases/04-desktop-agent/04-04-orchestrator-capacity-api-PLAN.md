---
phase: 04-desktop-agent
plan: 04
type: execute
wave: 2
depends_on: ["04-03"]
files_modified:
  - src/orchestrator/api.py
  - src/orchestrator/service.py
  - tests/test_orchestrator_capacity_api.py
autonomous: true
must_haves:
  truths:
    - "Orchestrator exposes GET /api/v1/agents/{agent_id}/capacity to query single agent capacity"
    - "Orchestrator exposes GET /api/v1/agents/available-capacity?min_gpu_vram_gb=X&min_cpu_cores=Y to find agents with available resources"
    - "Capacity endpoints return current resource metrics from database"
    - "Capacity queries filter by resource requirements and online status"
    - "WorkPlanner can use capacity queries to make GPU work routing decisions"
  artifacts:
    - path: src/orchestrator/api.py
      provides: "FastAPI endpoints for agent capacity queries"
      contains: "@app.get(\"/api/v1/agents/{agent_id}/capacity\")"
    - path: src/orchestrator/service.py
      provides: "OrchestratorService.get_agent_capacity() and get_available_capacity() methods"
      contains: "def get_available_capacity(self"
    - path: tests/test_orchestrator_capacity_api.py
      provides: "API tests for capacity endpoints (20+ test cases)"
      min_lines: 300
  key_links:
    - from: "WorkPlanner.generate_plan()"
      to: "GET /api/v1/agents/available-capacity"
      via: "Query before scheduling GPU work"
      pattern: "min_gpu_vram_gb"
    - from: "GET /api/v1/agents/available-capacity"
      to: "agent_registry.resource_metrics"
      via: "Database query filtering online agents"
      pattern: "status = 'online'"
---

<objective>
Add REST API endpoints for orchestrator to query agent capacity. WorkPlanner uses these endpoints before dispatching GPU-intensive work to ensure agents have required resources.

Purpose: Phase 3 WorkPlanner can check desktop agent availability but has no way to query resource capacity. Phase 4 requires capacity query endpoints so planner can make intelligent routing decisions based on GPU VRAM and CPU cores.

Output: Two new REST API endpoints + service methods + comprehensive test suite.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/04-desktop-agent/04-CONTEXT.md
@.planning/phases/04-desktop-agent/04-RESEARCH.md

## Capacity Query Patterns (from Research)

Endpoint 1: GET /api/v1/agents/{agent_id}/capacity
- Single agent capacity check
- Returns: agent_id, status, all current resource metrics
- Used by: Orchestrator debugging, WorkPlanner spot-checking
- Response 404 if agent not found

Endpoint 2: GET /api/v1/agents/available-capacity?min_gpu_vram_gb=X&min_cpu_cores=Y
- Multi-agent capacity search
- Filters: status=online, gpu_vram_available >= min_gpu_vram_gb, cpu_cores_available >= min_cpu_cores
- Returns: List of agents matching criteria with their capacity
- Used by: WorkPlanner to find agents for GPU work
- Query parameters all optional (default: 0 GPU, 1 CPU core)

## Integration with WorkPlanner (Phase 3)

After Phase 4, WorkPlanner can be updated (Phase 5 or later) to:
1. For GPU-bound tasks: Call GET /api/v1/agents/available-capacity?min_gpu_vram_gb=4.0
2. If no agents available: Mark task as "pending_capacity" (pause until agents available)
3. If agents available: Route task to agent with highest available VRAM

This is future work; Plan 04 just provides the endpoints.

## Database Query Optimization

resource_metrics is JSON column with structure:
```json
{
  "cpu_percent": 50.0,
  "cpu_cores_physical": 8,
  "cpu_cores_available": 4,
  "cpu_load_1min": 2.0,
  "cpu_load_5min": 1.5,
  "memory_percent": 60.0,
  "memory_available_gb": 4.5,
  "gpu_vram_total_gb": 8.0,
  "gpu_vram_available_gb": 4.0,
  "gpu_type": "nvidia"
}
```

Query: `SELECT * FROM agent_registry WHERE status='online' AND (resource_metrics->>'gpu_vram_available_gb')::float >= 4.0`

SQLAlchemy ORM approach:
- agent.resource_metrics is Python dict (loaded from JSON column)
- Use Python-side filtering: for agent in agents: if agent.resource_metrics.get('gpu_vram_available_gb', 0) >= min_vram
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add capacity query methods to OrchestratorService</name>
  <files>src/orchestrator/service.py</files>
  <action>
Add two methods to OrchestratorService class for capacity queries.

Method 1: get_agent_capacity(agent_id: UUID, db: Session) -> dict
```python
async def get_agent_capacity(self, agent_id: UUID, db: Session) -> dict:
    """Get single agent's current capacity.

    Args:
        agent_id: UUID of agent to query

    Returns:
        Dict with:
        {
            "agent_id": str(UUID),
            "status": "online" | "offline" | "busy",
            "cpu_cores_available": int,
            "cpu_cores_physical": int,
            "cpu_load_1min": float,
            "cpu_load_5min": float,
            "memory_available_gb": float,
            "gpu_vram_available_gb": float,
            "gpu_vram_total_gb": float,
            "gpu_type": str,
            "timestamp": ISO 8601
        }

    Raises:
        HTTPException(404) if agent not found (to be caught by API layer)
    """
```

Logic:
1. Query agent_registry by agent_id: db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()
2. If not found: raise AgentNotFoundError(agent_id) [define custom exception or let API layer return 404]
3. If found: Extract resource_metrics dict from agent.resource_metrics
4. Return dict with agent_id, status, all metrics from resource_metrics
5. Include last_heartbeat_at as timestamp
6. Log at DEBUG level

Error handling:
- If resource_metrics is None/empty: return zeros for all metrics
- Don't raise on empty metrics (agent may not have sent heartbeat yet)

Method 2: get_available_capacity(min_gpu_vram_gb: float = 0.0, min_cpu_cores: int = 1, db: Session = None) -> list[dict]
```python
async def get_available_capacity(
    self,
    min_gpu_vram_gb: float = 0.0,
    min_cpu_cores: int = 1,
    db: Session = None
) -> list[dict]:
    """Find agents with available capacity.

    Args:
        min_gpu_vram_gb: Minimum GPU VRAM required in GB (default 0, any GPU OK)
        min_cpu_cores: Minimum available CPU cores (default 1)
        db: Database session

    Returns:
        List of dicts, each with:
        {
            "agent_id": str(UUID),
            "agent_type": str,
            "pool_name": str,
            "status": "online",
            "gpu_vram_available_gb": float,
            "cpu_cores_available": int,
            "cpu_load_1min": float,
            "last_heartbeat_at": ISO 8601
        }
    """
```

Logic:
1. Query agents: db.query(AgentRegistry).filter(AgentRegistry.agent_type == "desktop", AgentRegistry.status == "online").all()
2. For each agent:
   - Extract resource_metrics dict
   - Get gpu_vram_available_gb = metrics.get("gpu_vram_available_gb", 0.0)
   - Get cpu_cores_available = metrics.get("cpu_cores_available", 1)
   - Check: gpu_vram_available_gb >= min_gpu_vram_gb AND cpu_cores_available >= min_cpu_cores
   - If matches: add to result list
3. Return result list (empty if no matches)
4. Log at INFO level: f"Found {len(result)} agents with capacity (min_gpu={min_gpu_vram_gb}GB, min_cpu={min_cpu_cores})"

Error handling:
- Skip agents with missing/malformed resource_metrics (log warning, don't crash)
- Don't raise exception (just return empty list if no agents match)

Do NOT:
- Change existing orchestrator methods
- Break RequestDecomposer, WorkPlanner, or AgentRouter
- Modify heartbeat handler
  </action>
  <verify>
Run: `python -c "from src.orchestrator.service import OrchestratorService; import inspect; src = inspect.getsource(OrchestratorService.get_agent_capacity); assert 'agent_id' in src"` (method exists)
Run: `python -c "from src.orchestrator.service import OrchestratorService; import inspect; src = inspect.getsource(OrchestratorService.get_available_capacity); assert 'min_gpu_vram_gb' in src"` (method exists)
Run: `grep -n "get_agent_capacity\|get_available_capacity" src/orchestrator/service.py` (both methods present)
  </verify>
  <done>
OrchestratorService.get_agent_capacity() and get_available_capacity() methods created. Both return expected dict structures. Query logic filters by status and resource metrics.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add FastAPI endpoints for capacity queries</name>
  <files>src/orchestrator/api.py</files>
  <action>
Add two new GET endpoints to FastAPI app in src/orchestrator/api.py for capacity queries.

Endpoint 1: GET /api/v1/agents/{agent_id}/capacity
```python
@app.get("/api/v1/agents/{agent_id}/capacity", response_model=dict, tags=["agents"])
async def get_agent_capacity(
    agent_id: str,
    db: Session = Depends(get_db),
    service: OrchestratorService = Depends(get_orchestrator_service)
) -> dict:
    """Get single agent's available capacity.

    Path parameters:
        - agent_id: UUID of agent to query

    Returns:
        {
            "agent_id": str,
            "status": "online" | "offline" | "busy",
            "cpu_cores_available": int,
            "cpu_cores_physical": int,
            "cpu_load_1min": float,
            "memory_available_gb": float,
            "gpu_vram_available_gb": float,
            "gpu_type": "nvidia|amd|intel|none",
            "timestamp": ISO 8601
        }

    Responses:
        - 200: Agent capacity
        - 404: Agent not found
        - 500: Database error
    """
    try:
        # Validate agent_id is UUID
        agent_uuid = UUID(agent_id)
        capacity = await service.get_agent_capacity(agent_uuid, db)
        return capacity
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id format (must be UUID)")
    except Exception as e:
        logger.error(f"Error fetching agent capacity: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch agent capacity")
```

Logic:
1. Parse agent_id parameter as UUID (validate format)
2. Call service.get_agent_capacity(agent_uuid, db)
3. Return result or raise HTTPException(404) if not found
4. Catch exceptions and return 500 if internal error

Endpoint 2: GET /api/v1/agents/available-capacity
```python
@app.get("/api/v1/agents/available-capacity", response_model=list[dict], tags=["agents"])
async def get_available_capacity(
    min_gpu_vram_gb: float = Query(0.0, ge=0.0, description="Minimum GPU VRAM in GB"),
    min_cpu_cores: int = Query(1, ge=1, description="Minimum available CPU cores"),
    db: Session = Depends(get_db),
    service: OrchestratorService = Depends(get_orchestrator_service)
) -> list[dict]:
    """Find agents with available capacity.

    Query parameters:
        - min_gpu_vram_gb: Minimum GPU VRAM required (default 0)
        - min_cpu_cores: Minimum available CPU cores (default 1)

    Returns:
        List of agents matching criteria:
        [
            {
                "agent_id": str,
                "agent_type": str,
                "pool_name": str,
                "status": "online",
                "gpu_vram_available_gb": float,
                "cpu_cores_available": int,
                "cpu_load_1min": float
            },
            ...
        ]

    Responses:
        - 200: List of agents (may be empty)
        - 400: Invalid parameters
        - 500: Database error
    """
    try:
        agents = await service.get_available_capacity(
            min_gpu_vram_gb=min_gpu_vram_gb,
            min_cpu_cores=min_cpu_cores,
            db=db
        )
        return agents
    except Exception as e:
        logger.error(f"Error fetching available capacity: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch available capacity")
```

Logic:
1. Validate query parameters (use Query with constraints: min_gpu_vram_gb >= 0, min_cpu_cores >= 1)
2. Call service.get_available_capacity(...)
3. Return list (empty if no matches)
4. Catch exceptions and return 500 if error

Integration notes:
- Add to existing app (from FastAPI setup in Phase 2)
- Use tags=["agents"] for Swagger docs grouping
- Use existing get_db and get_orchestrator_service dependencies
- Add logger for debugging

Do NOT:
- Override existing endpoints
- Change /api/v1/request, /api/v1/plan, /api/v1/status endpoints
- Break authentication/authorization (if added later)
  </action>
  <verify>
Run: `python -c "import ast; src = open('src/orchestrator/api.py').read(); tree = ast.parse(src); funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]; assert 'get_agent_capacity' in funcs and 'get_available_capacity' in funcs"` (endpoints defined)
Run: `grep -n "@app.get.*agents.*capacity" src/orchestrator/api.py` (endpoints have correct routes)
  </verify>
  <done>
FastAPI endpoints added. GET /api/v1/agents/{agent_id}/capacity and GET /api/v1/agents/available-capacity both available with proper parameter validation and error handling.
  </done>
</task>

<task type="auto">
  <name>Task 3: Create API endpoint tests (20+ test cases)</name>
  <files>tests/test_orchestrator_capacity_api.py