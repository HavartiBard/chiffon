# Phase 4: Desktop Agent (Resource Awareness) - Research

**Researched:** 2026-01-20
**Domain:** Lightweight desktop agent architecture, GPU/CPU resource metrics collection, heartbeat messaging, orchestrator capacity queries
**Confidence:** HIGH

## Summary

Phase 4 implements lightweight agents on GPU desktops that report real-time resource availability to the orchestrator. The design leverages existing BaseAgent framework (Phase 2), extends heartbeat messaging to include GPU VRAM/CPU metrics, and introduces agent capacity queries. The standard stack for resource monitoring uses `psutil` for CPU metrics (proven, 7.2.2 current) and `pynvml` (NVIDIA VRAM) with fallback to `nvidia-smi` for AMD/Intel portability.

**Key research findings:**

- **Resource metrics collection** is well-established: psutil for CPU metrics, pynvml for NVIDIA, nvidia-smi subprocess for cross-GPU portability
- **Heartbeat architecture** follows RabbitMQ patterns: 60s timeout with 30s interval (half-timeout), 2-3 consecutive misses before offline
- **Agent registry schema** in database already supports resource tracking; only needs migration to add resource_metrics JSON column
- **Orchestrator capacity queries** should use existing REST API pattern (parallel to current /api/v1/status endpoints)
- **BaseAgent already has metrics collection** (\_get_gpu_metrics, \_get_resource_metrics); Phase 4 extends this with better CPU reporting and configuration

**Primary recommendation:** Extend BaseAgent's resource collection methods, enable rolling average CPU load reporting (via psutil.getloadavg), add resource_metrics column to agent_registry table, and implement two new REST endpoints: `GET /api/v1/agents/{agent_id}/capacity` and `GET /api/v1/agents/available-capacity` for orchestrator queries.

---

## Standard Stack

### Core Libraries

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psutil | 7.2.2 | CPU load, core count, memory metrics | Battle-tested (10+ years), used in production monitoring (Netdata, Site24x7), cross-platform (Windows/Linux/macOS) |
| pynvml | 12.0.0+ (nvidia-ml-py) | NVIDIA GPU VRAM detection | Official NVIDIA bindings, faster than nvidia-smi subprocess, prevents zombie processes |
| aio-pika | (existing 9.0+) | RabbitMQ message dispatch | Already integrated in Phase 2, async-native |
| FastAPI | (existing 0.100+) | REST endpoints for capacity queries | Already integrated in Phase 2/3 for orchestrator API |

### Fallback Mechanisms

| Tool | Purpose | When Used |
|------|---------|-----------|
| nvidia-smi subprocess | NVIDIA GPU detection fallback | When pynvml unavailable (old CUDA versions), portable VRAM query |
| OS commands (lscpu, lstopo) | CPU topology discovery | Validate physical core count vs logical (hyperthreading) |
| psutil.cpu_affinity() | CPU core enumeration | Count physical cores only (conservative capacity) |

### Not in Standard Stack (Anti-patterns)

| Don't Use | Instead Use | Why |
|-----------|------------|-----|
| Custom GPU detection via WMI/direct APIs | pynvml + nvidia-smi fallback | Maintenance burden, vendor lock-in per GPU type |
| Instantaneous CPU percent (cpu_percent interval=0) | Load averages (getloadavg) + historical samples | Accurate scheduling decisions require trend data, not snapshots |
| Total minus active core calculation | Load percentage approach (load/cpu_count) | Avoids overcommitting during bursts |
| Hard-coded heartbeat intervals in agent code | Configuration-driven via config file | Enables tuning without code changes |

**Installation:**
```bash
pip install psutil pynvml
```

---

## Architecture Patterns

### Desktop Agent Role in Chiffon

```
┌─────────────────────────────────────────────────────────┐
│ GPU Desktop (Workstation/GPU Rig)                       │
├─────────────────────────────────────────────────────────┤
│ DesktopAgent (lightweight, async)                       │
│ ├─ Heartbeat sender: 30s interval                       │
│ ├─ Resource collector: GPU VRAM, CPU load              │
│ └─ Work executor: Phase 6 (for deployment work)        │
└─────────────────────────────────────────────────────────┘
                      │ (Heartbeat + metrics)
                      ▼ RabbitMQ
┌─────────────────────────────────────────────────────────┐
│ Orchestrator                                            │
├─────────────────────────────────────────────────────────┤
│ Agent Registry (DB) + Agent Router                      │
│ ├─ Tracks: agent_id, status, last_heartbeat            │
│ ├─ Extends: resource_metrics (GPU VRAM, CPU load)      │
│ └─ REST API: /agents/{id}/capacity                     │
└─────────────────────────────────────────────────────────┘
```

### Resource Metrics Data Format

Desktop agents report metrics in **StatusUpdate** messages (existing protocol, Phase 1):

```python
StatusUpdate(
    agent_id=UUID,
    agent_type="desktop",
    status="online",
    current_task_id=Optional[UUID],
    resources={
        "cpu_percent": float,           # Current CPU % (0-100)
        "cpu_cores_physical": int,      # Total physical cores
        "cpu_cores_available": int,     # Estimated available cores
        "cpu_load_1min": float,         # 1-min load average
        "cpu_load_5min": float,         # 5-min load average
        "memory_percent": float,        # RAM % (0-100)
        "memory_available_gb": float,   # Available RAM
        "gpu_vram_total_gb": float,     # GPU VRAM total
        "gpu_vram_available_gb": float, # GPU VRAM free
        "gpu_type": "nvidia|amd|intel|none",  # GPU vendor
    },
    timestamp=datetime.utcnow(),
)
```

**Why this format:**
- Raw values (GB, counts) allow orchestrator to apply logic, not locked into percentages
- Load averages (1m, 5m) enable trend-aware scheduling (prefer less trending-up agents)
- Physical cores only (conservative) prevents overcommitment
- GPU type enables vendor-specific fallback strategies

### Pattern 1: Heartbeat Loop with Exponential Backoff Reconnection

**What:** Agent maintains persistent RabbitMQ connection; if broken, exponential backoff (1s, 2s, 4s, ..., max 60s) to reconnect.

**When to use:** Critical for homelab stability; network blips are common, agents must survive brief disconnections without crashing.

**Example:**

```python
# Source: src/agents/base.py (existing, extend with reconnect logic)

async def _connect_with_backoff(self, max_retries: int = 10) -> None:
    """Connect to RabbitMQ with exponential backoff retry."""
    backoff_seconds = 1
    for attempt in range(max_retries):
        try:
            await self.connect()
            self.logger.info("Connected to RabbitMQ after backoff")
            return
        except aio_pika.exceptions.AMQPConnectionError as e:
            if attempt < max_retries - 1:
                self.logger.warning(
                    f"Connection attempt {attempt + 1} failed, "
                    f"retrying in {backoff_seconds}s: {e}"
                )
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 60)  # Cap at 60s
            else:
                self.logger.error(
                    f"Failed to connect after {max_retries} attempts, exiting"
                )
                raise

# In run() method:
async def run(self) -> None:
    try:
        await self._connect_with_backoff()
        # ... rest of agent loop
    except Exception as e:
        self.logger.error(f"Agent startup failed: {e}")
        exit(1)  # Force restart by systemd/supervisor
```

### Pattern 2: CPU Metrics via Load Average (Not Instantaneous Percent)

**What:** Report CPU load using `psutil.getloadavg()` (1-min, 5-min, 15-min) and derive available cores from load percentage.

**When to use:** Scheduling decisions benefit from trend awareness. Instantaneous CPU percent is noisy and leads to false "capacity" signals.

**Example:**

```python
# Source: Replace/extend _get_resource_metrics in BaseAgent

def _get_resource_metrics(self) -> dict[str, Any]:
    """Collect current resource metrics from system.

    Uses load averages (smoother than instant CPU%) and physical cores only.
    """
    try:
        cpu_count_physical = psutil.cpu_count(logical=False) or 1
        load_1min, load_5min, load_15min = psutil.getloadavg()

        # Current load percentage (bounded 0-100)
        load_percent = min(100.0, (load_1min / cpu_count_physical) * 100)

        # Available cores: estimate from load percentage
        available_cores = max(1, cpu_count_physical - (load_1min))  # Conservative

        metrics = {
            "cpu_percent": load_percent,
            "cpu_cores_physical": cpu_count_physical,
            "cpu_cores_available": available_cores,
            "cpu_load_1min": load_1min,
            "cpu_load_5min": load_5min,
            "memory_percent": psutil.virtual_memory().percent,
            "memory_available_gb": psutil.virtual_memory().available / (1024**3),
        }
        metrics.update(self._get_gpu_metrics())
        return metrics
    except Exception as e:
        self.logger.error(f"Error collecting resource metrics: {e}")
        return self._empty_metrics()
```

### Pattern 3: GPU Detection with Fallback Chain

**What:** Try pynvml (fast), fall back to nvidia-smi subprocess (portable), return zeros if no GPU.

**When to use:** Heterogeneous desktops (some NVIDIA, some AMD, some no GPU); must handle gracefully without crashes.

**Example:**

```python
# Source: Replace _get_gpu_metrics in BaseAgent

def _get_gpu_metrics(self) -> dict[str, float | str]:
    """Get GPU VRAM metrics with multi-vendor support.

    Tries: pynvml (NVIDIA, fastest) → nvidia-smi (AMD/Intel fallback) → zeros
    """
    # Try pynvml first (NVIDIA, fastest)
    try:
        import pynvml
        pynvml.nvmlInit()
        try:
            device_count = pynvml.nvmlDeviceGetCount()
            if device_count > 0:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                return {
                    "gpu_vram_total_gb": mem_info.total / (1024**3),
                    "gpu_vram_available_gb": mem_info.free / (1024**3),
                    "gpu_type": "nvidia",
                }
        finally:
            pynvml.nvmlShutdown()
    except (ImportError, Exception) as e:
        self.logger.debug(f"pynvml failed: {e}, trying nvidia-smi")

    # Fallback: nvidia-smi subprocess (works for AMD/Intel via ROCm/oneAPI)
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.free,name",
                "--format=csv,nounits,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 2:
                total_mb = float(parts[0])
                free_mb = float(parts[1])
                gpu_name = parts[2].strip().lower() if len(parts) > 2 else "unknown"

                gpu_type = "nvidia"  # Default (nvidia-smi is NVIDIA tool)
                if "amd" in gpu_name or "radeon" in gpu_name:
                    gpu_type = "amd"
                elif "intel" in gpu_name or "arc" in gpu_name:
                    gpu_type = "intel"

                return {
                    "gpu_vram_total_gb": total_mb / 1024.0,
                    "gpu_vram_available_gb": free_mb / 1024.0,
                    "gpu_type": gpu_type,
                }
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        self.logger.debug(f"nvidia-smi failed: {e}, no GPU detected")

    # No GPU available
    return {
        "gpu_vram_total_gb": 0.0,
        "gpu_vram_available_gb": 0.0,
        "gpu_type": "none",
    }
```

### Anti-Patterns to Avoid

- **Hardcoded heartbeat intervals:** Agent should read from config file (~/.chiffon/agent.yml), not code constants. Enables ops tuning without redeployment.
- **Measuring instantaneous CPU percent:** cpu_percent(interval=0) gives noise; use load averages for stable scheduling signals.
- **Requiring pynvml on all desktops:** Fall back to nvidia-smi subprocess; pynvml is optional optimization.
- **Storing full history in heartbeat messages:** Current state only; orchestrator aggregates history if needed.
- **Ignoring graceful shutdown:** Agent should attempt to notify orchestrator before dying; timeout-based offline detection is backup.

---

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| "Get CPU usage" | Parse /proc/stat or kernel APIs | psutil.cpu_percent() or psutil.getloadavg() | Cross-platform, handles multi-core aggregation correctly, tested in production |
| "Detect NVIDIA GPU VRAM" | Parse nvidia-smi output manually | pynvml library (official NVIDIA bindings) | Faster than subprocess, prevents zombie processes, handles driver timeouts |
| "Support AMD GPU detection" | Custom AMD ROCm parsing | nvidia-smi subprocess (works cross-vendor) + pyamdgpuinfo fallback | Portable, both NVIDIA and AMD use nvidia-smi interface, pynvml handles AMD indirectly |
| "Count physical cores only" | Parse lscpu output | psutil.cpu_count(logical=False) | Accurate, cross-platform, handles hyperthreading correctly |
| "RabbitMQ connection resilience" | Write custom retry logic | aio_pika.connect_robust() + exponential backoff | Library handles AMQP framing, auto-recovery, connection pooling |
| "Scheduling decisions based on load" | Invent custom capacity metric | Use load average % (load_1min / cpu_count) | Industry standard, works across scales, understood by ops teams |

**Key insight:** Resource metrics are deceptively complex when handling heterogeneous hardware. Subprocess calls can hang, GPU drivers can timeout, metrics snapshots are misleading. Always use vetted libraries + pragmatic fallbacks rather than rolling custom solutions.

---

## Common Pitfalls

### Pitfall 1: Trusting Instantaneous CPU Percent for Scheduling

**What goes wrong:** Agent reports CPU at 60%, orchestrator thinks 40% free. Thirty seconds later, load spikes to 95%. Task fails or takes 2x expected time.

**Why it happens:** `psutil.cpu_percent(interval=0)` measures system activity in the last 100ms; it's inherently noisy and doesn't reflect sustained demand.

**How to avoid:**
- Use load averages (`psutil.getloadavg()`) which reflect actual queued work
- Report both 1-min and 5-min averages so orchestrator can detect trends
- Derive "available cores" as `max(1, physical_cores - load_1min)` (conservative)
- Let orchestrator apply its own scheduling logic (e.g., "only schedule if 5-min load < 50%")

**Warning signs:**
- Orchestrator queues GPU work on an agent that looks idle (cpu_percent < 50%) but then work stalls
- Agents report 0% load consistently even during heavy training runs

### Pitfall 2: GPU Metrics Timeout Crashes Agent

**What goes wrong:** nvidia-smi subprocess hangs (GPU driver hang, locked GPU), agent crashes or stops sending heartbeats, orchestrator marks agent offline even though machine is fine.

**Why it happens:** GPU drivers can deadlock; nvidia-smi has no built-in timeout. Calling it without timeout in the heartbeat loop blocks the entire agent.

**How to avoid:**
- Always wrap subprocess calls with timeout (5s max): `subprocess.run(..., timeout=5)`
- Catch TimeoutExpired exception explicitly and return zeros (GPU temporarily unavailable)
- Use pynvml (library call, not subprocess) as primary path; it handles timeouts better
- Test GPU detection with a hung/reset GPU to ensure agent keeps running

**Warning signs:**
- Agent stops sending heartbeats after 5-10 mins (GPU driver hang)
- Logs show "Heartbeat loop error" with timeout exception
- Manual nvidia-smi takes >5s to return

### Pitfall 3: Offline Detection Too Slow (Missing Cascade Failures)

**What goes wrong:** Agent crashes at 10:00 AM. Orchestrator takes 3+ minutes to notice (waits for 2-3 consecutive missed heartbeats at 60s interval). During that time, new work gets queued to dead agent.

**Why it happens:** Conservative timeout (2+ heartbeats) prevents false positives from network jitter, but allows work pileup.

**How to avoid:**
- Use 90s offline threshold (3 × 30s heartbeat interval) as upper bound, not lower
- Implement fast path: agent sends explicit "going offline" message before shutdown (graceful), then timeout detection as backup
- Orchestrator should check agent status (call capacity query) before high-cost work dispatch
- For GPU-bound work, prefer re-checking capacity vs assuming agent still available

**Warning signs:**
- New tasks queued to offline agents (status in DB shows online but agent is dead)
- Cascading failures: one dead agent causes work to pile up while orchestrator waits for timeout

### Pitfall 4: Config Hardcoded in Agent Code

**What goes wrong:** Ops wants to test 60s heartbeat interval instead of 30s (reduce RabbitMQ load). Need to redeploy agent code instead of config file change.

**Why it happens:** Heartbeat interval is hardcoded in BaseAgent (`await asyncio.sleep(60)`).

**How to avoid:**
- All agent configuration (heartbeat interval, retry timeouts, RabbitMQ connection details) stored in config file: `~/.chiffon/agent.yml` or `/etc/chiffon/agent.yml`
- Agent reads config on startup and can be restarted with new config without code change
- Document default heartbeat interval (30s recommended) and allow override

**Warning signs:**
- Heartbeat interval or timeouts scattered through codebase (grep for `asyncio.sleep`)
- Ops team asks "how do we change heartbeat?" and answer is "modify Python code"

### Pitfall 5: Agent Registry Schema Missing Resource Metrics Column

**What goes wrong:** Heartbeat messages include resource metrics, but database schema doesn't store them. Metrics are lost; orchestrator can't query capacity.

**Why it happens:** Agent registry was created in Phase 3 for agent routing; resource metrics are Phase 4 addition. Schema not updated.

**How to avoid:**
- Create Alembic migration adding `resource_metrics JSON` column to agent_registry table
- Update agent heartbeat handler to save metrics to DB: `agent.resource_metrics = {"cpu_percent": ..., "gpu_vram_available_gb": ...}`
- Query capacity: `SELECT resource_metrics->>'gpu_vram_available_gb' FROM agent_registry WHERE agent_id = ?`

**Warning signs:**
- Agent sends metrics in heartbeat, but orchestrator can't retrieve them
- Orchestrator REST endpoint `/agents/{id}/capacity` returns empty/null resources

---

## Orchestrator Integration

### New Database Schema: Resource Metrics Column

**Migration (003_desktop_agent_resources.py):**

```sql
ALTER TABLE agent_registry
  ADD COLUMN resource_metrics JSON DEFAULT '{}';

CREATE INDEX idx_agent_registry_gpu_available
  ON agent_registry
  USING GIN (resource_metrics);
```

**Rationale:** JSON column allows flexible metric updates without schema changes; GIN index enables queries like "find agents with >4GB GPU VRAM".

### New REST Endpoints for Capacity Queries

**Endpoint 1: GET /api/v1/agents/{agent_id}/capacity**

Returns single agent's current capacity.

```python
# Source: src/orchestrator/api.py (extend existing routes)

@app.get("/api/v1/agents/{agent_id}/capacity", response_model=dict)
async def get_agent_capacity(agent_id: UUID, db: Session = Depends(get_db)):
    """Get single agent's available capacity.

    Returns:
        {
            "agent_id": UUID,
            "status": "online" | "offline" | "busy",
            "cpu_cores_available": int,
            "gpu_vram_available_gb": float,
            "gpu_type": "nvidia" | "amd" | "intel" | "none",
            "cpu_load_1min": float,
            "timestamp": ISO 8601,
        }
    """
    agent = db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not agent.resource_metrics:
        return {"error": "No resource metrics available"}

    return {
        "agent_id": str(agent.agent_id),
        "status": agent.status,
        **agent.resource_metrics,  # Unpack metrics dict
    }
```

**Endpoint 2: GET /api/v1/agents/available-capacity**

Returns all agents matching capacity filter (used by work planner).

```python
# Source: src/orchestrator/api.py

@app.get("/api/v1/agents/available-capacity", response_model=list[dict])
async def get_available_capacity(
    min_gpu_vram_gb: float = 0.0,
    min_cpu_cores: int = 1,
    db: Session = Depends(get_db),
):
    """Find agents with available capacity.

    Used by WorkPlanner to check if GPU-bound work can be scheduled.

    Query parameters:
        - min_gpu_vram_gb: Minimum GPU VRAM required (default 0, any GPU OK)
        - min_cpu_cores: Minimum available CPU cores (default 1)

    Returns:
        [
            {
                "agent_id": UUID,
                "pool_name": str,
                "gpu_vram_available_gb": float,
                "cpu_cores_available": int,
                "status": "online",
            },
            ...
        ]
    """
    agents = db.query(AgentRegistry).filter(
        AgentRegistry.agent_type == "desktop",
        AgentRegistry.status == "online",
    ).all()

    result = []
    for agent in agents:
        if not agent.resource_metrics:
            continue

        gpu_vram = agent.resource_metrics.get("gpu_vram_available_gb", 0.0)
        cpu_cores = agent.resource_metrics.get("cpu_cores_available", 1)

        if gpu_vram >= min_gpu_vram_gb and cpu_cores >= min_cpu_cores:
            result.append({
                "agent_id": str(agent.agent_id),
                "pool_name": agent.pool_name,
                "gpu_vram_available_gb": gpu_vram,
                "cpu_cores_available": cpu_cores,
                "status": agent.status,
            })

    return result
```

### Heartbeat Handler (Orchestrator Side)

**In OrchestratorService.handle_agent_heartbeat() (src/orchestrator/service.py):**

```python
async def handle_agent_heartbeat(
    self, heartbeat: StatusUpdate, db: Session
) -> None:
    """Process agent heartbeat and update registry.

    Called when agent sends heartbeat (work_status message type).
    Updates last_heartbeat_at and resource_metrics in DB.
    """
    agent = db.query(AgentRegistry).filter(
        AgentRegistry.agent_id == heartbeat.agent_id
    ).first()

    if not agent:
        # Auto-register new agent (homelab context: trust agents, monitor usage)
        agent = AgentRegistry(
            agent_id=heartbeat.agent_id,
            agent_type=heartbeat.agent_type,
            pool_name=f"{heartbeat.agent_type}_pool_1",  # Default pool
            capabilities=[],  # Will be populated by agent capabilities message
            status="online",
            last_heartbeat_at=func.now(),
        )
        db.add(agent)
    else:
        agent.status = "online"
        agent.last_heartbeat_at = func.now()

    # Store resource metrics
    agent.resource_metrics = heartbeat.resources  # JSON column

    db.commit()

    self.logger.info(
        f"Heartbeat from {heartbeat.agent_id}: "
        f"GPU {heartbeat.resources.get('gpu_vram_available_gb', 0):.1f}GB, "
        f"CPU {heartbeat.resources.get('cpu_load_1min', 0):.1f}%"
    )
```

---

## Testing Strategy

### Unit Tests: Resource Metrics Collection

**Location:** tests/test_desktop_agent_metrics.py

```python
class TestResourceMetrics:
    """Test resource metrics collection."""

    def test_cpu_metrics_load_average(self):
        """Verify CPU load average reporting."""
        metrics = agent._get_resource_metrics()
        assert "cpu_load_1min" in metrics
        assert "cpu_load_5min" in metrics
        assert 0.0 <= metrics["cpu_load_1min"] <= 999.0  # Unbounded
        assert metrics["cpu_cores_physical"] >= 1

    def test_gpu_metrics_nvidia(self, monkeypatch):
        """Test NVIDIA GPU detection via pynvml."""
        # Mock pynvml to return fixed VRAM
        def mock_get_memory_info(handle):
            class MemInfo:
                total = 8 * 1024 * 1024 * 1024  # 8GB
                free = 4 * 1024 * 1024 * 1024   # 4GB available
            return MemInfo()

        monkeypatch.setattr("pynvml.nvmlInit", lambda: None)
        monkeypatch.setattr("pynvml.nvmlDeviceGetCount", lambda: 1)
        monkeypatch.setattr("pynvml.nvmlDeviceGetHandleByIndex", lambda idx: "handle")
        monkeypatch.setattr("pynvml.nvmlDeviceGetMemoryInfo", mock_get_memory_info)
        monkeypatch.setattr("pynvml.nvmlShutdown", lambda: None)

        metrics = agent._get_gpu_metrics()
        assert metrics["gpu_type"] == "nvidia"
        assert metrics["gpu_vram_total_gb"] == 8.0
        assert metrics["gpu_vram_available_gb"] == 4.0

    def test_gpu_metrics_no_gpu_available(self):
        """Verify graceful handling when no GPU present."""
        metrics = agent._get_gpu_metrics()
        assert metrics["gpu_type"] == "none"
        assert metrics["gpu_vram_total_gb"] == 0.0
        assert metrics["gpu_vram_available_gb"] == 0.0

    def test_gpu_metrics_timeout_resilience(self, monkeypatch):
        """Verify nvidia-smi timeout doesn't crash agent."""
        def mock_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("nvidia-smi", 5)

        monkeypatch.setattr("subprocess.run", mock_timeout)
        monkeypatch.setattr("pynvml.nvmlInit", side_effect=ImportError())

        metrics = agent._get_gpu_metrics()  # Should not raise
        assert metrics["gpu_type"] == "none"
```

### Integration Tests: Heartbeat Messaging

**Location:** tests/test_desktop_agent_heartbeat.py

```python
class TestHeartbeatMessaging:
    """Test heartbeat message format and orchestrator handling."""

    async def test_heartbeat_message_format(self, test_agent):
        """Verify heartbeat includes all required resource fields."""
        # Trigger heartbeat send
        await test_agent.send_heartbeat()

        # Check message on reply queue
        message = await reply_queue.get()
        envelope = MessageEnvelope.from_json(message.body.decode())

        assert envelope.type == "work_status"
        status = StatusUpdate.model_validate(envelope.payload)

        assert status.agent_type == "desktop"
        assert status.status == "online"
        assert "cpu_load_1min" in status.resources
        assert "gpu_vram_available_gb" in status.resources

    async def test_heartbeat_loop_resilience(self, test_agent, monkeypatch):
        """Verify heartbeat loop survives metrics collection errors."""
        error_count = 0

        def mock_get_metrics():
            nonlocal error_count
            error_count += 1
            if error_count == 1:
                raise Exception("Simulated metrics error")
            return {"cpu_percent": 50.0}

        monkeypatch.setattr(test_agent, "_get_resource_metrics", mock_get_metrics)

        # Heartbeat loop should survive and send next heartbeat
        await test_agent.send_heartbeat()  # First call: error, handled
        await test_agent.send_heartbeat()  # Second call: success
```

### Integration Tests: Orchestrator Capacity Queries

**Location:** tests/test_orchestrator_capacity_api.py

```python
class TestCapacityQueries:
    """Test orchestrator REST API for capacity queries."""

    async def test_get_agent_capacity(self, client, db):
        """GET /api/v1/agents/{agent_id}/capacity returns capacity."""
        # Setup: register agent with resource metrics
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="gpu_pool_1",
            capabilities=[],
            status="online",
            resource_metrics={
                "gpu_vram_available_gb": 4.5,
                "cpu_cores_available": 8,
                "cpu_load_1min": 0.5,
            }
        )
        db.add(agent)
        db.commit()

        # Query capacity
        response = client.get(f"/api/v1/agents/{agent.agent_id}/capacity")
        assert response.status_code == 200
        data = response.json()

        assert data["gpu_vram_available_gb"] == 4.5
        assert data["cpu_cores_available"] == 8
        assert data["status"] == "online"

    async def test_get_available_capacity_filters(self, client, db):
        """GET /api/v1/agents/available-capacity filters by resources."""
        # Setup: 3 agents with different capacities
        agents = [
            {"gpu_vram": 8.0, "cpu_cores": 16},
            {"gpu_vram": 2.0, "cpu_cores": 4},
            {"gpu_vram": 0.0, "cpu_cores": 8},
        ]
        for i, cap in enumerate(agents):
            agent = AgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name="gpu_pool_1",
                capabilities=[],
                status="online",
                resource_metrics={
                    "gpu_vram_available_gb": cap["gpu_vram"],
                    "cpu_cores_available": cap["cpu_cores"],
                }
            )
            db.add(agent)
        db.commit()

        # Query: need >=4GB GPU VRAM
        response = client.get(
            "/api/v1/agents/available-capacity",
            params={"min_gpu_vram_gb": 4.0}
        )
        assert response.status_code == 200
        data = response.json()

        assert len(data) == 1  # Only agent with 8.0GB matches
        assert data[0]["gpu_vram_available_gb"] == 8.0
```

### Offline/Reconnect Scenario Testing

**Location:** tests/test_agent_offline_detection.py

```python
class TestOfflineDetection:
    """Test orchestrator offline detection and agent reconnection."""

    async def test_agent_marked_offline_after_missed_heartbeats(
        self, client, db
    ):
        """Agent marked offline after 3 consecutive missed heartbeats."""
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="gpu_pool_1",
            status="online",
            last_heartbeat_at=datetime.utcnow() - timedelta(seconds=150),  # 2.5min ago
        )
        db.add(agent)
        db.commit()

        # Orchestrator calls is_agent_online()
        is_online = orchestrator_service.is_agent_online(agent.agent_id)
        assert not is_online  # 150s > 90s threshold

    async def test_agent_reconnects_after_network_blip(
        self, test_agent, reply_queue
    ):
        """Agent resumes sending heartbeats after brief network interruption."""
        # Simulate network blip: agent disconnects for 30s
        original_connect = test_agent.connect

        async def mock_connect_with_delay():
            await asyncio.sleep(0.5)  # Simulate 30s network outage (compressed)
            return await original_connect()

        test_agent.connect = mock_connect_with_delay

        # Agent reconnects and sends heartbeat
        await test_agent.send_heartbeat()

        # Heartbeat should arrive on queue
        message = await asyncio.wait_for(reply_queue.get(), timeout=2.0)
        assert message is not None
```

---

## Code Examples

### Verified patterns from Phase 2/3 codebase (already tested):

**Pattern: Heartbeat Loop (Phase 2 BaseAgent)**

```python
# Source: src/agents/base.py (existing, proven in Phase 2)

async def start_heartbeat_loop(self) -> None:
    """Background task that sends heartbeats every 60 seconds."""
    try:
        while True:
            await asyncio.sleep(60)
            await self.send_heartbeat()
    except asyncio.CancelledError:
        self.logger.info("Heartbeat loop cancelled")
```

**Pattern: Status Update Message (Phase 1 Protocol)**

```python
# Source: src/common/protocol.py (existing)

class StatusUpdate(BaseModel):
    """Agent heartbeat status update."""
    agent_id: UUID
    agent_type: str = Field(pattern="^(orchestrator|infra|desktop|code|research)$")
    status: str = Field(pattern="^(online|offline|busy)$")
    current_task_id: Optional[UUID] = None
    resources: dict[str, Any] = {}  # Extend with GPU metrics
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

**Pattern: RabbitMQ Message Publishing (Phase 2)**

```python
# Source: src/agents/base.py (existing, proven)

async def send_heartbeat(self) -> None:
    """Send heartbeat via RabbitMQ to orchestrator."""
    envelope = MessageEnvelope(
        from_agent=self.agent_type,
        to_agent="orchestrator",
        type="work_status",
        priority=4,
        payload=status_update.model_dump(),
    )
    message = aio_pika.Message(body=envelope.to_json().encode())
    await self.reply_queue.channel.default_exchange.publish(
        message, routing_key=self.reply_queue.name
    )
```

---

## State of the Art

Current best practices for agent resource monitoring and heartbeats (2026):

| Approach | Status | Notes |
|----------|--------|-------|
| **Agent heartbeat intervals** | Active | 30-60s standard (RabbitMQ pattern), Celery uses similar, proven in production |
| **CPU load averages for scheduling** | Standard | Netdata, Prometheus, modern monitoring prefer getloadavg over instantaneous %; cross-platform |
| **pynvml for NVIDIA GPU detection** | Recommended | Official NVIDIA bindings, 12.0.0+ stable, faster than subprocess |
| **nvidia-smi fallback for AMD/Intel** | Pragmatic | Portable, works with AMD ROCm and Intel oneAPI, handles multi-vendor heterogeneity |
| **psutil for system metrics** | Battle-tested | 10+ years, production use in Netdata/Prometheus/Site24x7, only option for cross-platform CPU |
| **Agent auto-registration on heartbeat** | Emerging | Homelab-friendly pattern, reduces operational overhead (manual registration not needed) |
| **Capacity queries via REST API** | Standard | FastAPI/modern frameworks, Kubernetes-inspired pattern (node capacity API) |

**Deprecated/outdated:**
- Custom shell scripts for resource detection (fragile, slow, platform-specific)
- WMI for GPU detection outside Windows (platform lock-in)
- Parsing /proc/stat manually (error-prone, Linux-only, complex logic)
- Instantaneous CPU percent for scheduling (noisy, doesn't reflect sustained demand)

---

## Risk Assessment

### Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| GPU driver hang freezes agent heartbeat | MEDIUM | HIGH | 5s timeout on nvidia-smi, use pynvml when possible, explicit metrics error handling |
| Heterogeneous GPU support (NVIDIA/AMD/Intel) | MEDIUM | MEDIUM | Test fallback chain on each GPU type, graceful "no GPU" case, log detection failures |
| Load average anomalies on heavily oversubscribed systems | LOW | MEDIUM | Document assumption (physical cores only, conservative), monitor outliers, allow config override |
| Agent offline detection lag (3+ minutes) | LOW | MEDIUM | Implement graceful shutdown message, fast-path capacity check before dispatch, monitor heartbeat staleness |
| Resource metrics JSON schema changes | MEDIUM | LOW | Use additive schema (new fields don't break existing queries), migrate empty values to 0.0, test queries on schema variations |

### Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| Agents run out of sync (different heartbeat intervals) | MEDIUM | LOW | All agents read interval from config file, ops can check consistency via API, document defaults |
| Orchestrator over-commits work to agent (ignores capacity) | MEDIUM | HIGH | Make capacity query mandatory before GPU work dispatch, add assertion in WorkPlanner |
| RabbitMQ outage disconnects all agents simultaneously | MEDIUM | MEDIUM | aio_pika.connect_robust handles reconnection, exponential backoff prevents stampede, monitor connection pool size |

### Dependencies

- **psutil 7.2.2+**: Critical (CPU metrics), well-maintained, active upstream
- **pynvml 12.0.0+ (nvidia-ml-py)**: Optional (NVIDIA optimization), older versions deprecated, fallback to nvidia-smi
- **aio_pika**: Already integrated Phase 2, handles RabbitMQ complexity
- **subprocess (Python stdlib)**: Always available, no new dependency

---

## Open Questions

1. **Auto-register vs Manual Approval?**
   - **What we know:** CONTEXT.md says "auto-register with monitoring" (homelab context)
   - **What's unclear:** Should orchestrator require agent registration confirmation before routing work?
   - **Recommendation:** AUTO-REGISTER on first heartbeat, but log all registrations and alert ops if unknown agent connects. Phase 5 (State & Audit) can add manual approval gates later if needed.

2. **Heartbeat Interval Configurability?**
   - **What we know:** CONTEXT.md says 30s interval/90s timeout is default, "can be tuned without phase re-planning"
   - **What's unclear:** How configurable (env var vs config file vs REST API)?
   - **Recommendation:** Config file (~/.chiffon/agent.yml) with defaults, env vars for Docker override, no REST API needed (restart agent to change).

3. **Resource Metrics Storage Retention?**
   - **What we know:** Current metrics are transient (live in agent_registry.resource_metrics column)
   - **What's unclear:** Do we need historical trending (e.g., "agent's GPU load over last hour")?
   - **Recommendation:** Phase 4 = current state only. Phase 5 (State & Audit) can add time-series table if trending analysis needed for post-mortems.

4. **Multi-GPU Support?**
   - **What we know:** CONTEXT.md focuses on single GPU per desktop
   - **What's unclear:** Do we report aggregate VRAM for multi-GPU systems (total - used) or per-GPU?
   - **Recommendation:** Phase 4 = aggregate (easier). Phase 6 (Infrastructure Agent) can specialize work to specific GPUs if needed.

5. **Temperature/Fan Metrics?**
   - **What we know:** CONTEXT.md says "minimal resource-only metrics (CPU load, GPU VRAM, cores); temperature deferred"
   - **What's unclear:** Should thermal monitoring be added for safety?
   - **Recommendation:** Phase 4 = skip thermal. Phase 5 can add alerts if thermal data becomes critical for failures.

---

## Sources

### Primary (HIGH confidence)

- **psutil documentation** (7.2.2) — https://psutil.readthedocs.io/
  - CPU load averages, core counting, memory metrics

- **pynvml GitHub** — https://github.com/gpuopenanalytics/pynvml
  - NVIDIA GPU VRAM detection, official NVML bindings

- **RabbitMQ Heartbeats documentation** — https://www.rabbitmq.com/docs/heartbeats
  - Heartbeat timeout/interval relationship, missed heartbeat detection

- **Chiffon codebase (Phase 1-3)** — src/agents/base.py, src/common/protocol.py, src/orchestrator/router.py
  - Existing BaseAgent framework, StatusUpdate message format, agent registry schema

### Secondary (MEDIUM confidence)

- **WebSearch: Python GPU detection cross-platform 2026** — [WebSearch results]
  - Confirmed nvidia-smi fallback pattern, pyOpenCL for cross-vendor, pynvml performance advantage

- **WebSearch: Python CPU metrics load average 2026** — [WebSearch results]
  - Confirmed psutil as standard, getloadavg vs cpu_percent distinction, load-based scheduling patterns

- **WebSearch: Agent heartbeat messaging RabbitMQ 2026** — [WebSearch results]
  - Confirmed 30s interval (half of 60s timeout), 2-3 consecutive misses for offline threshold, exponential backoff patterns

### Tertiary (referenced but not fetched)

- FastAPI capacity query patterns — https://fastapi.tiangolo.com/
  - REST endpoint design patterns, async query handling (already know from Phase 2/3 implementation)

---

## Metadata

**Confidence breakdown:**
- Standard stack (psutil, pynvml, RabbitMQ patterns): **HIGH** — verified via official docs, codebase patterns proven in Phase 2/3
- Architecture patterns (heartbeat loop, resource metrics, GPU fallback): **HIGH** — based on battle-tested patterns (Netdata, Prometheus, Kubernetes), aligned with Phase 1-3 design
- Pitfalls: **HIGH** — from real-world homelab GPU scenarios and documented in monitoring tools (nvidia-smi timeouts, CPU noise)
- Orchestrator integration: **MEDIUM** — REST API pattern established in Phase 3, but specific capacity endpoint design is Phase 4 contribution

**Research date:** 2026-01-20
**Valid until:** 2026-02-20 (stable domain, 30 days conservative estimate; psutil/pynvml change slowly)

**Notes:**
- Phase 4 is data-path (metrics flow from agent→orchestrator), not compute-path (work execution)
- Heartbeat/metrics system is orthogonal to Phase 6 (Infrastructure Agent work execution)
- All resource metrics are immediateable by design; orchestrator can aggregate historical data in Phase 5
- Testing strategy focuses on realistic GPU/CPU scenarios (timeouts, heterogeneous hardware, offline scenarios)
