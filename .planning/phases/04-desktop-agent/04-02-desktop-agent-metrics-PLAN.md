---
phase: 04-desktop-agent
plan: 02
type: execute
wave: 2
depends_on: ["04-01"]
files_modified:
  - src/agents/desktop_agent.py
  - src/common/config.py
  - ~/.chiffon/agent.yml
autonomous: true
must_haves:
  truths:
    - "Desktop agent reports CPU load averages (1-min, 5-min) instead of instantaneous percent"
    - "Desktop agent reports available CPU cores calculated from load percentage"
    - "Desktop agent reports GPU VRAM with multi-vendor support (NVIDIA via pynvml, AMD/Intel via nvidia-smi fallback)"
    - "Desktop agent reads heartbeat config from file (~/.chiffon/agent.yml), not hardcoded"
    - "Desktop agent gracefully handles GPU timeouts and metrics collection errors"
  artifacts:
    - path: src/agents/desktop_agent.py
      provides: "DesktopAgent class extending BaseAgent with enhanced resource metrics"
      min_lines: 150
    - path: src/common/config.py
      provides: "Configuration loading for heartbeat interval, timeout, GPU detection strategy"
      contains: "heartbeat_interval_seconds"
    - path: ~/.chiffon/agent.yml
      provides: "Default config file for agent deployment"
      contains: "heartbeat_interval_seconds: 30"
  key_links:
    - from: "DesktopAgent._get_resource_metrics()"
      to: "psutil.getloadavg() + psutil.cpu_count()"
      via: "CPU load-based available core calculation"
      pattern: "getloadavg"
    - from: "DesktopAgent._get_gpu_metrics()"
      to: "pynvml (primary) + nvidia-smi (fallback)"
      via: "Multi-vendor GPU detection with timeouts"
      pattern: "pynvml|nvidia-smi.*timeout"
---

<objective>
Extend BaseAgent with production-grade resource metrics collection for desktop agents. Implement CPU load averages (not instantaneous %), GPU detection with multi-vendor support and timeouts, and configuration-driven heartbeat intervals.

Purpose: Phase 2 BaseAgent has basic metrics, but uses instantaneous CPU % (noisy for scheduling) and lacks multi-GPU support. Phase 4 requires stable, accurate metrics for orchestrator routing decisions.

Output: DesktopAgent class ready for instantiation, config loader for operational tunability, example config file.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/04-desktop-agent/04-CONTEXT.md
@.planning/phases/04-desktop-agent/04-RESEARCH.md

## Metrics Collection Standards (from Research)

CPU Metrics (psutil):
- Load averages (psutil.getloadavg()): 1-min, 5-min, 15-min
- Physical cores (psutil.cpu_count(logical=False)): Conservative capacity
- Available cores: max(1, physical_cores - load_1min) for conservative scheduling

GPU Metrics (Multi-vendor):
1. Try pynvml (NVIDIA, fastest)
2. Fall back to nvidia-smi subprocess (AMD/Intel via ROCm/oneAPI, portable)
3. Return zeros if no GPU

Timeout handling: All subprocess calls must have 5s timeout to prevent agent hangs.

## Config File Location

~/.chiffon/agent.yml (user home) or /etc/chiffon/agent.yml (system), with defaults:
- heartbeat_interval_seconds: 30 (send status every 30s)
- heartbeat_timeout_seconds: 90 (mark offline if 3 consecutive misses)
- gpu_detection_timeout_seconds: 5 (nvidia-smi max runtime)
- agent_id: auto-generated UUID (hostname for display)

## Pitfalls to Avoid (from Research)

1. Instantaneous CPU percent (cpu_percent(interval=0)): Use load averages instead
2. GPU detection hangs: Always wrap subprocess with timeout
3. Hard-coded config: All timing params from config file
4. Ignoring pynvml import errors: Graceful fallback to nvidia-smi
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create DesktopAgent class with enhanced resource metrics</name>
  <files>src/agents/desktop_agent.py</files>
  <action>
Create new file src/agents/desktop_agent.py implementing DesktopAgent class that extends BaseAgent.

DesktopAgent must override:
1. _get_resource_metrics(): Return dict with CPU load averages, available cores, memory, GPU metrics
   - Use psutil.getloadavg() for 1-min, 5-min load averages (not cpu_percent)
   - Calculate available cores: max(1, physical_cores - load_1min)
   - Include cpu_load_1min, cpu_load_5min, cpu_cores_physical, cpu_cores_available
   - Include memory_percent and memory_available_gb
   - Call _get_gpu_metrics() and merge into dict

2. _get_gpu_metrics(): Return GPU VRAM with multi-vendor support
   - Try pynvml first (NVIDIA, fastest):
     - Import pynvml, nvmlInit()
     - Get device count and first device
     - Get memory info (total, free)
     - Return {"gpu_vram_total_gb": X, "gpu_vram_available_gb": Y, "gpu_type": "nvidia"}
     - Handle ImportError and any pynvml exceptions gracefully
   - Fallback to nvidia-smi subprocess if pynvml unavailable:
     - Run: nvidia-smi --query-gpu=memory.total,memory.free,name --format=csv,nounits,noheader
     - Timeout: 5 seconds (CRITICAL - prevent agent hang)
     - Parse output: total_mb, free_mb, gpu_name
     - Detect GPU type from name: nvidia (default), amd (radeon), intel (arc/oneapi)
     - Return dict with converted GB values
   - Return zeros if both fail: {"gpu_vram_total_gb": 0.0, "gpu_vram_available_gb": 0.0, "gpu_type": "none"}

3. get_agent_capabilities(): Return supported work types for desktop agents
   - For Phase 4, return empty dict {} (actual work execution in Phase 6)
   - Include placeholder for future: {"gpu_compute": False, "inference": False, "training": False}

4. execute_work(): Stub for Phase 4 (actual work in Phase 6)
   - Log that work_type is received
   - Return success with output "Desktop agent phase 4 (metrics only)"
   - No actual execution yet

Constructor changes:
- Accept config: Config object
- Read heartbeat_interval_seconds from config (default 30)
- Read gpu_detection_timeout_seconds from config (default 5)

Imports needed:
- subprocess, logging, asyncio
- psutil (7.2.2+)
- pynvml (optional import with fallback)
- from src.agents.base import BaseAgent
- from src.common.protocol import WorkRequest, WorkResult
- from src.common.config import Config

Exception handling:
- Wrap all GPU detection in try/except (pynvml errors, subprocess timeout, parse errors)
- Log errors at DEBUG level (don't crash agent on metrics collection failure)
- Return sensible defaults (zeros) if any collection fails

Logging:
- Debug log on pynvml import failure
- Debug log on nvidia-smi timeout
- Info log on successful metrics collection (with sample values)

Code organization:
- About 200-250 lines
- Clear section comments: GPU Detection, CPU Metrics, Error Handling
- Docstrings on all methods
  </action>
  <verify>
Run: `python -c "from src.agents.desktop_agent import DesktopAgent; print(DesktopAgent)"` (class imports)
Run: `python -c "from src.agents.desktop_agent import DesktopAgent; d = DesktopAgent('test-agent', 'desktop', config); m = d._get_resource_metrics(); print(m.keys())"` (verify all keys present: cpu_percent, cpu_load_1min, cpu_load_5min, cpu_cores_physical, cpu_cores_available, memory_percent, gpu_vram_total_gb, gpu_vram_available_gb, gpu_type)
Run: `python -c "from src.agents.desktop_agent import DesktopAgent; d = DesktopAgent('test-agent', 'desktop', config); g = d._get_gpu_metrics(); assert 'gpu_type' in g and 'gpu_vram_available_gb' in g"` (GPU metrics structure valid)
  </verify>
  <done>
DesktopAgent class created with CPU load averages, available core calculation, multi-vendor GPU support, timeout handling. All methods return expected data structures. No import errors.
  </done>
</task>

<task type="auto">
  <name>Task 2: Update Config class to load heartbeat parameters from file</name>
  <files>src/common/config.py</files>
  <action>
Update Config class in src/common/config.py to load heartbeat and GPU detection parameters from config file.

Changes:
1. Add new fields to Config class:
   - heartbeat_interval_seconds: int (default 30)
   - heartbeat_timeout_seconds: int (default 90)
   - gpu_detection_timeout_seconds: int (default 5)
   - agent_id: str (default generated from hostname)
   - agent_pool_name: str (default "desktop_pool_1")

2. Add config file search logic in __init__():
   - Check ~/.chiffon/agent.yml first (user home directory)
   - Check /etc/chiffon/agent.yml second (system config)
   - Check environment variables for override (CHIFFON_HEARTBEAT_INTERVAL, etc.)
   - Use defaults if no file found

3. Add YAML parsing:
   - Use yaml.safe_load() to parse config file
   - Validate config dict has expected keys (use .get() with defaults)
   - Log which config file was loaded

4. Add env var override capability:
   - os.getenv("CHIFFON_HEARTBEAT_INTERVAL") overrides file value
   - os.getenv("CHIFFON_AGENT_ID") overrides generated/file value

5. Do NOT:
   - Break existing database or RabbitMQ config loading
   - Change class name or constructor signature too much
   - Remove any existing fields

Example config structure in file:
```yaml
# Heartbeat settings
heartbeat_interval_seconds: 30
heartbeat_timeout_seconds: 90

# GPU detection
gpu_detection_timeout_seconds: 5

# Agent identification
agent_id: "gpu-rig-1"  # Or leave blank for auto-generate from hostname
agent_pool_name: "desktop_pool_1"
```

Imports needed:
- yaml
- pathlib.Path
- os
- hostname detection (socket.gethostname())
  </action>
  <verify>
Run: `python -c "from src.common.config import Config; c = Config(); print(f'heartbeat: {c.heartbeat_interval_seconds}, timeout: {c.heartbeat_timeout_seconds}, gpu_timeout: {c.gpu_detection_timeout_seconds}')"` (config loads with defaults)
Run: `mkdir -p ~/.chiffon && echo 'heartbeat_interval_seconds: 60' > ~/.chiffon/agent.yml && python -c "from src.common.config import Config; c = Config(); assert c.heartbeat_interval_seconds == 60"` (config file override works)
Run: `CHIFFON_HEARTBEAT_INTERVAL=45 python -c "from src.common.config import Config; c = Config(); assert c.heartbeat_interval_seconds == 45"` (env var override works)
  </verify>
  <done>
Config class loads heartbeat parameters from ~/.chiffon/agent.yml, /etc/chiffon/agent.yml, or env vars. Defaults work. File-based override works. Env var override works.
  </done>
</task>

<task type="auto">
  <name>Task 3: Create example config file (~/.chiffon/agent.yml)</name>
  <files>~/.chiffon/agent.yml</files>
  <action>
Create example config file at ~/.chiffon/agent.yml for agent deployment.

File should contain:
```yaml
# Chiffon Desktop Agent Configuration
# Location: ~/.chiffon/agent.yml or /etc/chiffon/agent.yml

# Heartbeat Settings
# Interval: How often to send status updates (seconds)
# Timeout: Mark agent offline after this many seconds without heartbeat
# Rule of thumb: timeout = 3 * interval
heartbeat_interval_seconds: 30
heartbeat_timeout_seconds: 90

# GPU Detection
# Max time to wait for GPU detection tools (nvidia-smi, pynvml)
# Prevents agent hang if GPU driver is unresponsive
gpu_detection_timeout_seconds: 5

# Agent Identification
# agent_id: Leave blank or set to UUID for auto-generation, or set hostname/custom name
# agent_pool_name: Group agents by pool for scheduling (e.g., desktop_pool_1, gpu_rig_1)
agent_id: ""  # Leave blank for auto-generate from hostname
agent_pool_name: "desktop_pool_1"

# RabbitMQ (optional - can use environment variables)
# rabbitmq_host: localhost
# rabbitmq_port: 5672
# rabbitmq_user: guest
# rabbitmq_password: guest

# Database (optional - can use environment variables)
# database_url: postgresql://user:password@localhost:5432/chiffon
```

Also document in comments:
- Default behavior: generate UUID from hostname if agent_id blank
- Multiple agents can share same pool_name (orchestrator groups by pool)
- Heartbeat interval 30s recommended for homelab (30s = 2 msgs/min = 2880/day per agent)
- GPU detection timeout should match system responsiveness (5s = aggressive timeout, 10s = lenient)

File permissions: Readable by agent user (chmod 640 or 644).

Create the file with sensible defaults (all commented, agent_id blank for auto-generate).
  </action>
  <verify>
Run: `cat ~/.chiffon/agent.yml` (file exists and is readable)
Run: `grep "heartbeat_interval_seconds: 30" ~/.chiffon/agent.yml` (correct default)
Run: `grep "gpu_detection_timeout_seconds: 5" ~/.chiffon/agent.yml` (correct default)
Run: `yaml.safe_load(open(Path.home() / '.chiffon' / 'agent.yml')) | python -c "import yaml, sys; data = yaml.safe_load(sys.stdin); print(data.get('heartbeat_interval_seconds', 'NOT FOUND'))"` (YAML parses)
  </verify>
  <done>
Example config file created at ~/.chiffon/agent.yml with sensible defaults and documentation. File is valid YAML and parseable by Python.
  </done>
</task>

</tasks>

<verification>
1. DesktopAgent class created and imports successfully
2. CPU metrics use load averages (not instantaneous percent)
3. Available cores calculated conservatively from load percentage
4. GPU detection tries pynvml first, falls back to nvidia-smi, returns zeros if unavailable
5. All subprocess calls have 5s timeout
6. Config loads from ~/.chiffon/agent.yml with proper defaults
7. Env vars can override config file settings
8. Example config file exists and is valid YAML
9. No errors when instantiating DesktopAgent with Config
</verification>

<success_criteria>
- DesktopAgent class provides enhanced resource metrics collection
- CPU metrics based on load averages (stable for scheduling)
- GPU detection multi-vendor with graceful fallbacks
- All resource collection is timeout-safe (prevents agent hangs)
- Config file loadable from ~/.chiffon/agent.yml with env var override
- Example config file documents all parameters
- Ready for Plan 03 (heartbeat loop integration)
</success_criteria>

<output>
After completion, create `.planning/phases/04-desktop-agent/04-02-SUMMARY.md` with:
- DesktopAgent implementation details (metrics collection strategy)
- Config file handling approach
- Timeout protection strategy
- Example usage and instantiation
- Ready-for-Plan-03 status
</output>
