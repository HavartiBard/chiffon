# Phase 3: Orchestrator Core - Research

**Researched:** 2026-01-19
**Domain:** Natural language request parsing, work plan generation, agent routing and capability matching, external AI fallback logic
**Confidence:** HIGH (verified with official docs, current frameworks, and production patterns)

## Summary

Phase 3 delivers the orchestrator's core intelligence: accepting natural language requests, decomposing them into executable work plans, routing to appropriate agents based on capability and resource availability, and falling back to Claude when local reasoning is insufficient.

This research covers:
- **NLU & Request Parsing:** Direct LLM-based decomposition (Claude/Ollama) is simpler and more flexible than rule-based parsing for this domain
- **Work Plan Generation:** Sequential task lists with dependency tracking, resource requirements, and reordering based on availability
- **Agent Routing:** Pool-based assignment with performance tracking in PostgreSQL, supporting weighted load balancing and failure retry
- **External AI Fallback:** Complexity + quota-based triggers using LiteLLM's built-in tracking and cost management
- **Architecture:** Request → Parse → Plan → Route → Execute pattern, with full audit logging at each decision point

**Primary recommendation:** Use Claude/Ollama directly for NLU decomposition (faster to build, more flexible), persist agent performance in PostgreSQL with a simple agent_performance table, implement fallback via LiteLLM quota checks + complexity assessment in orchestrator service layer.

---

## Standard Stack

### Core Libraries

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | ^0.104.0 | REST API + dependency injection | Already in Phase 2; async-first, excellent for service orchestration |
| Pydantic v2 | ^2.0.0 | Request/response validation, work plan schemas | Strict validation prevents invalid plans; already integrated |
| LiteLLM | ^1.0.0 | Claude/Ollama routing, cost tracking, quota management | Unified interface for local + external LLMs; built-in cost tracking and fallback |
| SQLAlchemy | ^2.0.0 | ORM for agent registry + performance tracking | Already in Phase 1; supports async operations |
| PostgreSQL | 13+ | Agent registry, performance history, audit logs | Already deployed; excellent for relational data (capabilities, performance metrics) |
| aio-pika | ^9.5 | RabbitMQ async client | Already integrated; handles work dispatch |
| asyncio | Python 3.11+ stdlib | Event loop for concurrent work dispatch | Standard Python; no additional dependency |

### Testing Framework

| Library | Version | Purpose |
|---------|---------|---------|
| pytest | ^7.4.0 | Unit and integration test runner |
| pytest-asyncio | ^0.21.0 | Async test support |
| unittest.mock | Python stdlib | Mock agents and LLM services |

### No External NLU Libraries Required

**Decision:** Do NOT add spaCy, Rasa, or Hugging Face transformers.

**Why:** For orchestrator's narrow use case (decomposing requests into 2-5 subtasks for known agents), direct Claude/Ollama prompting is simpler and more flexible than training an NLU pipeline. This aligns with Phase 3 scope: "best guess + present to user" rather than perfect NLU accuracy. Future phases can add sophisticated NLU if needed, but v1 should optimize for autonomy and speed, not accuracy on edge cases.

---

## Architecture Patterns

### Request Processing Pipeline

```
1. User submits: "Deploy Kuma and add existing portals to config"
                    ↓
2. Orchestrator.accept_request()
   - Assign request_id
   - Validate language (basic checks)
                    ↓
3. NLU.decompose()
   - Call Claude/Ollama with decomposition prompt
   - Extract: [Task 1: Deploy Kuma, Task 2: Configure portals]
   - Confidence: [0.95, 0.88]
                    ↓
4. Orchestrator.assess_complexity()
   - For each subtask, determine: simple/medium/complex
   - Decide: use Ollama vs Claude for planning
                    ↓
5. WorkPlanner.generate_plan()
   - For each task, determine: work_type, parameters, resource_needs, agent_type
   - Order based on dependency + resource availability
   - Result: sequential task list with alternatives
                    ↓
6. Agent execution (dispatch_work → agents handle work)
```

### Request Decomposition (NLU)

**Approach:** Direct LLM-based decomposition via prompt engineering.

**Implementation:**

```python
# In orchestrator/nlu.py
class RequestDecomposer:
    def __init__(self, llm_client: LiteLLMClient):
        self.llm = llm_client

    async def decompose(self, request: str, user_context: dict) -> DecomposedRequest:
        """Decompose natural language request into subtasks.

        Prompt engineering handles:
        - Multi-task detection ("Deploy X AND add Y")
        - Task ordering (understand dependencies)
        - Confidence scoring (0.0-1.0 per subtask)
        - Unknown task detection (log out-of-scope requests)

        Returns: {
            "subtasks": [
                {"order": 1, "name": "Deploy Kuma", "intent": "deploy_kuma", "confidence": 0.95},
                {"order": 2, "name": "Configure portals", "intent": "add_portals_to_config", "confidence": 0.88}
            ],
            "ambiguities": ["Should we use staging or production?"],
            "out_of_scope": []
        }
        """
        prompt = self._build_decomposition_prompt(request, user_context)
        response = await self.llm.call_llm(
            model="claude-opus-4.5",  # or ollama/neural-chat for cost
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2  # Low temp for deterministic decomposition
        )

        # Parse response JSON
        parsed = json.loads(response["choices"][0]["message"]["content"])
        return DecomposedRequest(**parsed)

    def _build_decomposition_prompt(self, request: str, context: dict) -> str:
        """Build structured prompt for decomposition.

        Include: request text, known agent types, example decompositions, format constraints.
        """
        return f"""
You are an orchestrator assistant. Decompose this request into subtasks.

Request: "{request}"

Known agent types: deploy_service, add_configuration, run_automation, monitor_system

Guidelines:
1. Break complex requests into 2-5 sequential subtasks
2. For each subtask, assign confidence (0.0-1.0)
3. Flag ambiguities ("unclear if should use X or Y")
4. Flag out-of-scope work

Return JSON: {{"subtasks": [...], "ambiguities": [...], "out_of_scope": [...]}}
"""
```

**Key Design Decisions (from CONTEXT.md):**
- Automatic decomposition without user confirmation (except for ambiguities)
- Log out-of-scope requests with frequency tracking → future feature request detection
- Support request templates ("kuma-deploy") for quick shortcuts
- Per-interaction explanation verbosity control

### Work Plan Generation

**Approach:** Sequential task list with resource requirements and dependency-based reordering.

**Schema:**

```python
# In common/models.py
class WorkTask(BaseModel):
    """Single task in an execution plan."""
    order: int
    name: str
    work_type: str  # e.g., "deploy_service", "run_playbook"
    agent_type: str  # e.g., "infra", "code", "research"
    parameters: dict
    resource_requirements: dict = {
        "estimated_duration_seconds": int,
        "gpu_vram_mb": int,
        "cpu_cores": int,
    }
    depends_on: list[int] = []  # Task orders this depends on
    alternatives: list[dict] = []  # If resource unavailable, try these

class WorkPlan(BaseModel):
    """Complete execution plan for a request."""
    plan_id: UUID
    request_id: UUID
    tasks: list[WorkTask]
    estimated_duration_seconds: int
    complexity_level: str  # "simple", "medium", "complex"
    will_use_external_ai: bool
    status: str = "pending_approval"
    created_at: datetime
```

**Generation Algorithm:**

```python
# In orchestrator/planner.py
class WorkPlanner:
    async def generate_plan(self, decomposed: DecomposedRequest, agent_pool: AgentPool) -> WorkPlan:
        """Generate executable plan from decomposed request.

        Steps:
        1. For each subtask, create WorkTask(s) with resource requirements
        2. Check resource availability (via agent_pool.get_available_resources())
        3. Reorder tasks if needed (low-resource tasks run while waiting for GPU)
        4. Assess complexity (simple task = Ollama, complex = Claude)
        5. Return plan with alternatives for unavailable resources
        """
        tasks = []

        for i, subtask in enumerate(decomposed.subtasks):
            # Step 1: Create task with best-guess resource needs
            task = await self._create_task(subtask, i + 1)

            # Step 2: Check resource availability
            available = await agent_pool.can_satisfy_resources(task.resource_requirements)
            if not available:
                # Step 3: Offer alternatives
                task.alternatives = await self._suggest_alternatives(task)

            tasks.append(task)

        # Step 4: Reorder tasks based on dependencies + resource availability
        tasks = self._reorder_by_resources(tasks, agent_pool)

        # Step 5: Assess complexity
        complexity = self._assess_complexity([t.work_type for t in tasks])
        will_use_claude = complexity == "complex"

        return WorkPlan(
            plan_id=uuid4(),
            request_id=decomposed.request_id,
            tasks=tasks,
            estimated_duration_seconds=sum(t.resource_requirements.get("estimated_duration_seconds", 60) for t in tasks),
            complexity_level=complexity,
            will_use_external_ai=will_use_claude,
        )

    async def _create_task(self, subtask: dict, order: int) -> WorkTask:
        """Create WorkTask from decomposed subtask intent.

        Map intent → work_type + agent_type using config/mapping.
        Estimate resources based on work_type.
        """
        intent_to_work_type = {
            "deploy_kuma": ("deploy_service", "infra", {"estimated_duration_seconds": 180, "gpu_vram_mb": 0, "cpu_cores": 2}),
            "add_portals_to_config": ("run_playbook", "infra", {"estimated_duration_seconds": 60, "gpu_vram_mb": 0, "cpu_cores": 1}),
            # More mappings...
        }

        work_type, agent_type, resources = intent_to_work_type.get(
            subtask.get("intent"),
            ("custom_work", "research", {"estimated_duration_seconds": 120, "gpu_vram_mb": 0, "cpu_cores": 1})
        )

        return WorkTask(
            order=order,
            name=subtask.get("name"),
            work_type=work_type,
            agent_type=agent_type,
            parameters=subtask.get("parameters", {}),
            resource_requirements=resources,
        )
```

**Design Pattern: Resource-Aware Scheduling**

CONTEXT.md decision: "Reorder steps based on resource availability: run low-resource steps while waiting for GPU availability."

```python
def _reorder_by_resources(self, tasks: list[WorkTask], agent_pool: AgentPool) -> list[WorkTask]:
    """Reorder tasks to maximize resource utilization.

    If GPU unavailable but CPU task available, run CPU task first.
    Example:
    - Task 1: GPU inference (needs 8GB VRAM, not available)
    - Task 2: Config update (needs 0GB, available)
    → Reorder to Task 2 → Task 1
    """
    # Separate tasks by resource availability
    ready = [t for t in tasks if agent_pool.can_satisfy_resources(t.resource_requirements)]
    blocked = [t for t in tasks if not agent_pool.can_satisfy_resources(t.resource_requirements)]

    # Return ready tasks first, then blocked tasks
    # In practice, more sophisticated reordering considering dependency DAGs
    return ready + blocked
```

### Agent Routing & Capability Matching

**Approach:** Pool-based routing with performance tracking in PostgreSQL.

**Database Schema:**

```sql
-- Agent Registry
CREATE TABLE agent_registry (
    agent_id UUID PRIMARY KEY,
    agent_type VARCHAR(50) NOT NULL,  -- infra, code, research, desktop
    pool_name VARCHAR(100) NOT NULL,  -- e.g., "infra_pool_1", "gpu_pool"
    capabilities JSON NOT NULL,  -- ["deploy_service", "run_playbook", "ansible"]
    specializations JSON,  -- e.g., ["config_specialist", "deployment_expert"]
    status VARCHAR(50) DEFAULT 'offline',  -- online, offline, busy
    last_heartbeat_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

-- Agent Performance Tracking
CREATE TABLE agent_performance (
    id SERIAL PRIMARY KEY,
    agent_id UUID REFERENCES agent_registry(agent_id),
    work_type VARCHAR(100),  -- e.g., "deploy_service"
    success_count INT DEFAULT 0,
    failure_count INT DEFAULT 0,
    total_duration_ms INT DEFAULT 0,  -- For computing average
    last_execution_at TIMESTAMP,
    difficulty_assessment VARCHAR(50),  -- "straightforward", "tricky", "failed"
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(agent_id, work_type)
);

-- Routing Decisions (Audit Trail)
CREATE TABLE routing_decisions (
    id SERIAL PRIMARY KEY,
    task_id UUID,
    work_type VARCHAR(100),
    agent_pool VARCHAR(100),
    selected_agent_id UUID REFERENCES agent_registry(agent_id),
    success_rate_percent INT,
    specialization_match BOOLEAN,
    recent_context_match BOOLEAN,
    retried BOOLEAN DEFAULT false,
    reason TEXT,
    created_at TIMESTAMP DEFAULT now()
);
```

**Routing Algorithm:**

```python
# In orchestrator/router.py
class AgentRouter:
    def __init__(self, db: Session, agent_pool: AgentPool):
        self.db = db
        self.pool = agent_pool

    async def route_task(self, task: WorkTask, retry_count: int = 0) -> AgentSelection:
        """Route task to best available agent.

        Criteria (in order):
        1. Must be online and have capability
        2. Prefer agents with recent context (similar recent tasks)
        3. Prefer agents with higher success rate
        4. Prefer specialized agents if available
        5. Fall back to round-robin load balancing within pool
        """

        # Step 1: Find agents in target pool that are online + have capability
        candidates = self.db.query(agent_registry).filter(
            agent_registry.agent_type == task.agent_type,
            agent_registry.status.in_(["online", "idle"]),
            agent_registry.capabilities.contains(task.work_type)
        ).all()

        if not candidates:
            # No agents available in pool
            raise ValueError(f"Agent pool {task.agent_type} is offline/empty for {task.work_type}")

        # Step 2: Score candidates
        scores = {}
        for candidate in candidates:
            score = 0

            # Recent context bonus
            recent_context = self._check_recent_context(candidate, task.work_type)
            score += 30 if recent_context else 0

            # Success rate
            perf = self.db.query(agent_performance).filter(
                agent_performance.agent_id == candidate.agent_id,
                agent_performance.work_type == task.work_type
            ).first()
            if perf:
                success_rate = perf.success_count / (perf.success_count + perf.failure_count) if perf.success_count + perf.failure_count > 0 else 0.5
                score += int(success_rate * 40)  # 40 points max

            # Specialization match
            if task.work_type in (candidate.specializations or []):
                score += 20

            # Load balancing (prefer less busy)
            current_load = self._estimate_load(candidate)
            score += max(0, 10 - current_load)

            scores[candidate.agent_id] = score

        # Step 3: Select best agent
        best_agent_id = max(scores, key=scores.get)
        best_agent = next(c for c in candidates if c.agent_id == best_agent_id)

        # Step 4: Log routing decision
        self._log_routing_decision(task, best_agent, scores[best_agent_id], retry_count)

        return AgentSelection(
            agent_id=best_agent_id,
            agent_type=best_agent.agent_type,
            pool_name=best_agent.pool_name,
            selected_reason=f"Score: {scores[best_agent_id]}, Success rate: {perf.success_count if perf else 'N/A'}"
        )

    def _check_recent_context(self, agent: AgentRegistry, work_type: str) -> bool:
        """Did agent recently handle similar work?"""
        recent = self.db.query(routing_decisions).filter(
            routing_decisions.selected_agent_id == agent.agent_id,
            routing_decisions.work_type == work_type,
            routing_decisions.created_at > datetime.utcnow() - timedelta(hours=4)
        ).first()
        return recent is not None

    def _log_routing_decision(self, task, agent, score, retry_count):
        """Audit log every routing decision."""
        self.db.add(routing_decisions(
            task_id=task.order,
            work_type=task.work_type,
            agent_pool=agent.pool_name,
            selected_agent_id=agent.agent_id,
            success_rate_percent=int(score),
            retried=retry_count > 0,
            reason=f"Best score: {score}/100"
        ))
        self.db.commit()
```

**Failure Retry:**

```python
async def dispatch_with_retry(self, task: WorkTask, max_retries: int = 3) -> dict:
    """Dispatch task with automatic retry on different agent."""
    for attempt in range(max_retries):
        try:
            selection = await self.route_task(task, retry_count=attempt)
            result = await self.dispatch_work(
                task_id=task.id,
                agent_id=selection.agent_id,
                work_type=task.work_type,
                parameters=task.parameters
            )
            return result
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Attempt {attempt + 1} failed, retrying on different agent: {e}")
                continue
            else:
                logger.error(f"All {max_retries} attempts failed")
                raise
```

### External AI Fallback Logic

**Approach:** Complexity + quota-based assessment using LiteLLM's built-in tracking.

**Decision Criteria (from CONTEXT.md):**
- Use Claude if: complexity = "high" OR remaining_quota < 20%
- Quota tracking via LiteLLM's `/user/info` endpoint
- Silent operation (no user notification)
- All decisions logged in audit trail

**Implementation:**

```python
# In orchestrator/fallback.py
class ExternalAIFallback:
    def __init__(self, litellm_client: LiteLLMClient, config: Config):
        self.llm = litellm_client
        self.config = config
        self.logger = logging.getLogger("orchestrator.fallback")

    async def should_use_external_ai(self, task: WorkTask, plan: WorkPlan) -> tuple[bool, str]:
        """Determine if task should use Claude instead of local Ollama.

        Returns: (use_claude, reason)
        """

        # Check quota first (fastest check)
        remaining_quota = await self._get_remaining_quota()
        if remaining_quota < 0.20:  # Less than 20% remaining
            self.logger.info(f"Using Claude due to low quota: {remaining_quota:.1%} remaining")
            return True, "quota_critical"

        # Check complexity
        complexity = plan.complexity_level  # "simple", "medium", "complex"
        if complexity == "complex":
            self.logger.info(f"Using Claude due to complexity: {complexity}")
            return True, "high_complexity"

        # Default: use local Ollama
        return False, "local_sufficient"

    async def _get_remaining_quota(self) -> float:
        """Check remaining quota via LiteLLM API.

        Returns: fraction of remaining calls (0.0 = exhausted, 1.0 = full)
        """
        try:
            # LiteLLM tracks quota per API key
            # Use /user/info endpoint to check spending vs budget
            user_info = await self.llm.get_user_quota(
                api_key=self.config.LITELLM_MASTER_KEY
            )

            total_spend = user_info.get("total_spend_usd", 0)
            max_budget = user_info.get("max_budget_usd", 1000)  # Default 1000

            remaining_budget = max(0, max_budget - total_spend)
            remaining_fraction = remaining_budget / max_budget if max_budget > 0 else 1.0

            return remaining_fraction
        except Exception as e:
            self.logger.warning(f"Could not check quota: {e}; defaulting to local")
            return 1.0  # Safe default: assume unlimited

    async def call_external_ai_with_fallback(self, prompt: str, task_context: dict):
        """Call Claude, fall back to Ollama if Claude fails.

        Workflow:
        1. Try Claude (primary)
        2. If timeout/error: try Ollama (fallback)
        3. If both fail: raise exception
        """
        try:
            # Try Claude first
            self.logger.info(f"Calling Claude for task: {task_context.get('name')}")
            response = await self.llm.call_llm(
                model="claude-opus-4.5",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2000
            )

            # Log Claude usage for cost tracking
            self._log_llm_usage("claude-opus-4.5", task_context)
            return response

        except (TimeoutError, requests.Timeout) as e:
            # Timeout: try Ollama
            self.logger.warning(f"Claude timeout, falling back to Ollama: {e}")
            try:
                response = await self.llm.call_llm(
                    model="ollama/neural-chat",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                )
                self._log_llm_usage("ollama/neural-chat", task_context)
                return response
            except Exception as fallback_error:
                self.logger.error(f"Both Claude and Ollama failed: {fallback_error}")
                raise

        except Exception as e:
            # Other Claude error: try Ollama
            self.logger.warning(f"Claude error, trying Ollama: {e}")
            try:
                response = await self.llm.call_llm(
                    model="ollama/neural-chat",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                )
                self._log_llm_usage("ollama/neural-chat", task_context)
                return response
            except Exception as fallback_error:
                self.logger.error(f"Ollama also failed: {fallback_error}")
                raise

    def _log_llm_usage(self, model: str, task_context: dict):
        """Log which LLM was used for audit trail."""
        task_id = task_context.get("task_id")
        self.db.query(Task).filter(Task.task_id == task_id).update({
            "external_ai_used": {
                "model": model,
                "timestamp": datetime.utcnow().isoformat()
            }
        })
        self.db.commit()
```

**Batch Claude Calls (Optional, Phase 3 scope: simple batching):**

```python
class BatchedExternalAICaller:
    """Batch multiple related tasks into single Claude call for efficiency."""

    async def batch_planning_calls(self, tasks: list[WorkTask]) -> list[dict]:
        """Group logically-related tasks, call Claude once with all context."""

        # Simple heuristic: group by task type
        grouped = {}
        for task in tasks:
            work_type = task.work_type
            if work_type not in grouped:
                grouped[work_type] = []
            grouped[work_type].append(task)

        # Call Claude once per group
        results = {}
        for work_type, group_tasks in grouped.items():
            prompt = self._build_batch_prompt(work_type, group_tasks)
            response = await self.llm.call_llm(
                model="claude-opus-4.5",
                messages=[{"role": "user", "content": prompt}]
            )
            results[work_type] = response

        return results

    def _build_batch_prompt(self, work_type: str, tasks: list[WorkTask]) -> str:
        task_list = "\n".join([f"- {t.name}" for t in tasks])
        return f"""
Plan execution strategy for these {work_type} tasks:
{task_list}

Provide one unified plan considering all tasks.
"""
```

---

## Don't Hand-Roll

Problems that appear simple but have significant complexity:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NLU decomposition | Custom regex/rule parser | Claude/Ollama direct call | Human language is too ambiguous; LLM handles edge cases naturally |
| Work plan validation | Manual DAG checker | Pydantic validators + simple cycle detection | Validation logic grows fast (dependencies, circular refs, resource conflicts) |
| Agent performance tracking | In-memory cache | PostgreSQL with agent_performance table | Need persistence across restarts, historical trend analysis, query flexibility |
| Cost/quota tracking | Manual accounting in code | LiteLLM's built-in quota system + `/user/info` endpoint | Tracking state across async calls is error-prone; LiteLLM's database-backed tracking is authoritative |
| Load balancing | Simple round-robin | Weighted selection based on success rate + recent context | Round-robin ignores agent reliability; failures increase over time; context-aware routing reduces retry cycles |
| Request idempotency | Request cache in orchestrator | Database-persisted request tracking | In-memory cache lost on restart; database provides durable deduplication |

**Key insight:** Orchestration is a **state machine with lots of side effects** (LLM calls, agent dispatch, DB updates). Every decision point creates potential for bugs if not properly tracked. Use existing, proven tools (LiteLLM, SQLAlchemy, PostgreSQL) rather than custom logic.

---

## Common Pitfalls

### Pitfall 1: Over-Decomposing Requests

**What goes wrong:** Orchestrator breaks "Deploy Kuma and configure portals" into 5+ subtasks when 2-3 would suffice. User's plan becomes incomprehensible.

**Why it happens:** Decomposition prompt is too aggressive, or logic tries to decompose each parameter separately.

**How to avoid:**
- Prompt engineering: "Create 2-5 subtasks minimum. Group related work."
- Confidence threshold: Only decompose if decomposer confidence > 0.80
- User review step: Show decomposition plan to user before execution; allow merging/editing

**Warning signs:**
- Work plan exceeds 5-10 tasks for single user request
- Task names become overly granular ("Create deployment PR", "Wait for CI", "Merge PR" vs just "Deploy via CI")

### Pitfall 2: Complexity Assessment Too Pessimistic

**What goes wrong:** Orchestrator marks simple tasks as "complex", always falls back to Claude, burning quota unnecessarily.

**Why it happens:** Complexity heuristic too conservative (e.g., any task with >10 parameters = complex).

**How to avoid:**
- Define clear thresholds: complexity = "complex" IFF work_type in ["research", "architecture_review"] OR task involves >3 agent handoffs
- A/B test actual success rates: track if Ollama succeeds at tasks marked "simple" or fails at tasks marked "complex"
- Log complexity assessments with outcomes for post-mortem analysis

**Warning signs:**
- 30%+ of tasks fallback to Claude
- Agent performance logs show Ollama succeeding at >90% of "simple" tasks but only 40% of "medium" tasks

### Pitfall 3: Agent Pool Offline Not Caught Early

**What goes wrong:** All infra agents offline, but orchestrator doesn't detect until attempting dispatch, causing user to wait and then get cryptic "agent offline" error.

**How to avoid:**
- **Health check before planning:** Check agent pool availability before generating work plan
- Reject request at NLU stage if target pool is offline: "Infra agents currently offline. Cannot proceed."
- Per-request timeout: If all retries exhaust in <5 mins, return early with clear error

**Warning signs:**
- User complains: "I submitted request, waited 2 minutes, then got error"
- Orchestrator logs show dispatch_work attempt with zero agents available

### Pitfall 4: Routing Decisions Not Auditable

**What goes wrong:** Task fails, user asks "Why was agent X selected?" but orchestrator has no log explaining decision.

**How to avoid:**
- Log **every routing decision** with: task_id, selected_agent_id, success_rate, specialization_match, reason
- Include in task status response: routing audit trail (user visible for transparency)
- Use structured logging (JSON format) for easy queries later

**Warning signs:**
- No `routing_decisions` table queries in post-mortem analysis
- User can't see why their task was routed to a particular agent

### Pitfall 5: Quota Exhaustion Without Warning

**What goes wrong:** Orchestrator exhausts Claude quota silently, subsequent requests fall back to Ollama with degraded quality, user doesn't notice until system behaves poorly.

**How to avoid:**
- Check quota **before** executing expensive tasks
- Set quota alarm: If <10% remaining, log warning (not user-facing)
- Proactive communication: When quota hits 20%, notify (audit log only, not user UI)
- Graceful degradation: Automatically switch to Ollama for "simple" tasks only when quota low

**Warning signs:**
- External_ai_used logs show majority of tasks using Claude after a certain point
- Cost tracking shows unexpectedly high spend in a single day

### Pitfall 6: Fallback to Ollama Fails But Not Retried

**What goes wrong:** Claude timeout → fallback to Ollama → Ollama also fails → request fails entirely (no third attempt).

**How to avoid:**
- Implement **three-tier fallback:**
  1. Try Claude (primary)
  2. On failure → Try Ollama (fallback)
  3. On failure → Queue for manual review (don't lose work)
- Set explicit timeout per tier (e.g., 30s for Claude, 15s for Ollama)
- Log all fallback attempts with timestamps for debugging

**Warning signs:**
- Request failures clustered around times of Claude/Ollama service issues
- No evidence of retry attempts in logs

### Pitfall 7: Performance Metrics Skewed by Incomplete Data

**What goes wrong:** Agent success_rate calculated as 5/7 = 71% based on only 7 executions; new agent appears reliable but actually statistically unreliable.

**How to avoid:**
- **Minimum sample size:** Only use success rate after agent has executed work_type at least 10 times
- **Confidence intervals:** Store std deviation alongside average duration
- **Tie-breaking:** If success rates tied, prefer agent with more executions

**Warning signs:**
- New agents consistently routed over experienced agents despite fewer executions
- High variance in task duration (agent A: 30-300s for same task)

---

## Code Examples

### Request Decomposition

```python
# In orchestrator/nlu.py
from pydantic import BaseModel

class DecomposedRequest(BaseModel):
    """Result of request decomposition."""
    request_id: UUID
    subtasks: list[dict]  # [{"order": 1, "name": "...", "intent": "...", "confidence": 0.95}]
    ambiguities: list[str]
    out_of_scope: list[str]

class RequestDecomposer:
    async def decompose(self, request: str) -> DecomposedRequest:
        """Decompose natural language request.

        Example input: "Deploy Kuma Uptime and add our existing portals to config"
        Example output:
        {
            "request_id": "uuid-...",
            "subtasks": [
                {"order": 1, "name": "Deploy Kuma Uptime", "intent": "deploy_kuma", "confidence": 0.95},
                {"order": 2, "name": "Add portals to config", "intent": "add_portals_to_config", "confidence": 0.88}
            ],
            "ambiguities": [],
            "out_of_scope": []
        }
        """
        prompt = f"""
You are a request decomposition assistant for an infrastructure orchestration system.

Decompose this user request into 2-5 subtasks.

Request: "{request}"

For each subtask, provide:
1. order (1, 2, 3, ...)
2. name (clear description)
3. intent (recognized work type)
4. confidence (0.0-1.0)

Known intents: deploy_kuma, add_portals_to_config, run_playbook, deploy_service, run_automation

Return JSON: {{"subtasks": [...], "ambiguities": [...], "out_of_scope": [...]}}
"""

        response = await self.llm.call_llm(
            model="claude-opus-4.5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=500
        )

        content = response["choices"][0]["message"]["content"]
        data = json.loads(content)

        return DecomposedRequest(
            request_id=uuid4(),
            subtasks=data["subtasks"],
            ambiguities=data.get("ambiguities", []),
            out_of_scope=data.get("out_of_scope", [])
        )
```

### Work Plan Generation with Resource Ordering

```python
# In orchestrator/planner.py
class WorkPlanner:
    async def generate_plan(self, decomposed: DecomposedRequest, agent_pool) -> WorkPlan:
        """Generate executable plan with resource-aware task ordering."""

        tasks = []
        for i, subtask in enumerate(decomposed.subtasks, start=1):
            work_type = subtask["intent"]

            # Map intent to work parameters
            work_def = self._get_work_definition(work_type)

            task = WorkTask(
                order=i,
                name=subtask["name"],
                work_type=work_type,
                agent_type=work_def["agent_type"],
                parameters=subtask.get("parameters", {}),
                resource_requirements=work_def["resources"],
            )
            tasks.append(task)

        # Reorder by resource availability
        available_resources = await agent_pool.get_available_resources()
        tasks = self._reorder_by_availability(tasks, available_resources)

        # Assess complexity for fallback decision
        complexity = self._assess_complexity([t.work_type for t in tasks])

        return WorkPlan(
            plan_id=uuid4(),
            request_id=decomposed.request_id,
            tasks=tasks,
            estimated_duration_seconds=sum(
                t.resource_requirements.get("estimated_duration_seconds", 60)
                for t in tasks
            ),
            complexity_level=complexity,
            will_use_external_ai=(complexity == "complex"),
            status="pending_approval"
        )

    def _reorder_by_availability(self, tasks: list[WorkTask], resources: dict) -> list[WorkTask]:
        """Reorder tasks so low-resource tasks run while waiting for high-resource tasks."""

        ready = []
        blocked = []

        for task in tasks:
            req = task.resource_requirements
            can_run = (
                resources.get("available_gpu_vram_mb", 0) >= req.get("gpu_vram_mb", 0)
                and resources.get("available_cpu_cores", 0) >= req.get("cpu_cores", 0)
            )

            if can_run:
                ready.append(task)
            else:
                blocked.append(task)

        # Return ready tasks first, maintaining dependency order
        result = ready + blocked

        # Re-number orders
        for i, task in enumerate(result, start=1):
            task.order = i

        return result

    def _assess_complexity(self, work_types: list[str]) -> str:
        """Assess if plan is simple/medium/complex for fallback decision."""

        # Simple heuristic
        complex_types = {"research", "code_gen", "architecture_review"}

        if any(wt in complex_types for wt in work_types):
            return "complex"

        if len(work_types) > 3:
            return "medium"

        return "simple"
```

### Agent Routing with Performance Tracking

```python
# In orchestrator/router.py, integrated with the work dispatch flow

async def dispatch_work_with_routing(
    self,
    task: WorkTask,
    trace_id: UUID,
    max_retries: int = 3
) -> dict:
    """Dispatch work to selected agent with audit logging."""

    for attempt in range(max_retries):
        try:
            # Select best agent
            selection = await self.router.route_task(task, retry_count=attempt)

            # Create work request
            work_req = WorkRequest(
                task_id=task.id,
                work_type=task.work_type,
                parameters=task.parameters,
            )

            envelope = MessageEnvelope(
                from_agent="orchestrator",
                to_agent=selection.agent_type,
                type="work_request",
                trace_id=trace_id,
                request_id=uuid4(),
                payload=work_req.model_dump()
            )

            # Dispatch via RabbitMQ
            await self.channel.default_exchange.publish(
                aio_pika.Message(body=envelope.to_json().encode()),
                routing_key=f"work_{selection.agent_type}"
            )

            self.logger.info(
                f"Dispatched to {selection.agent_id}",
                extra={
                    "trace_id": str(trace_id),
                    "task_id": str(task.id),
                    "agent_id": str(selection.agent_id),
                    "attempt": attempt + 1
                }
            )

            return {
                "trace_id": str(trace_id),
                "task_id": str(task.id),
                "agent_id": str(selection.agent_id),
                "status": "dispatched"
            }

        except ValueError as e:
            if "Agent pool offline" in str(e):
                # Permanent error: don't retry
                self.logger.error(f"Agent pool offline for {task.agent_type}")
                raise
            else:
                # Temporary error: retry
                if attempt < max_retries - 1:
                    self.logger.warning(f"Routing failed, retry: {e}")
                    continue
                else:
                    raise
```

---

## State of the Art

| Old Approach | Current Approach (2026) | When Changed | Impact |
|--------------|------------------------|--------------|--------|
| Hard-coded task dispatch | LLM-based decomposition | 2023+ | Enables natural language requests, eliminates hardcoded workflow templates |
| Batch job scheduling | Async task routing with resource awareness | 2024+ | Better resource utilization, faster execution of independent tasks |
| Single fallback LLM | Multi-tier fallback (Claude → Ollama → queue) | 2025+ | Cost optimization, resilience to any single LLM failure |
| Manual agent pool management | Automatic pool health checks + dynamic routing | 2025+ | Graceful degradation, early detection of offline pools |
| Blob cost tracking | Granular quota tracking per key + spend alerts | 2025+ | Prevents runaway costs, enables intelligent fallback decisions |
| Unstructured decision logs | Audit-grade routing decision tables | 2026 | Enables post-mortem analysis, transparency for users |

---

## Open Questions

### Question 1: Confidence Threshold for Decomposition

**Status:** Claude's Discretion (CONTEXT.md)

**What we know:**
- Decomposer outputs confidence per subtask (0.0-1.0)
- Low confidence → present ambiguities to user
- But at what threshold do we reject the entire plan?

**What's unclear:**
- If average confidence < 0.75, reject decomposition and ask user to clarify?
- Or always show plan even if confidence low, marking ambiguous tasks?

**Recommendation for Phase 3:**
- Use simple threshold: if any subtask < 0.60 confidence, flag as ambiguity
- If >2 flagged ambiguities, require user approval before proceeding
- Log threshold decisions for later tuning

### Question 2: Load Balancing Strategy (Round-Robin vs Weighted)

**Status:** Claude's Discretion (CONTEXT.md)

**What we know:**
- Need to distribute work across agent pools
- Can use round-robin (fair, predictable) or weighted (optimized, based on performance)

**What's unclear:**
- Which performs better in practice?
- Round-robin simpler, weighted more sophisticated; what's the actual gain?

**Recommendation for Phase 3:**
- Implement **weighted selection** (based on success rate + recent context)
- Default heuristic: success_rate * 0.6 + context_match * 0.4
- Log actual vs predicted outcomes to measure effectiveness
- Can switch to round-robin if weighted adds too much complexity

### Question 3: Resource Estimation Accuracy

**What we know:**
- Each work_type has estimated resource requirements
- Actual requirements vary (estimated 60s, actual could be 40-90s)

**What's unclear:**
- How to handle over-estimates (task finishes early, blocks next task)?
- How to detect under-estimates (task exceeds resources, crashes)?

**Recommendation for Phase 3:**
- Track actual_resources in WorkResult
- After each task execution, update work_type resource estimates using exponential smoothing
- Example: new_estimate = 0.7 * old_estimate + 0.3 * actual_duration
- This learns actual resource usage over time

### Question 4: Dependency Modeling (Sequential vs DAG)

**What we know:**
- CONTEXT.md defers DAG support to Phase 5
- Phase 3 uses sequential task lists

**What's unclear:**
- What if tasks are genuinely independent (can run in parallel)?
- How to represent "run task 2 OR task 3 depending on task 1's output"?

**Recommendation for Phase 3:**
- Keep it simple: sequential task list only
- Add optional `depends_on: list[int]` field in WorkTask for future flexibility
- If a task has no dependencies, always execute in order (no parallelization)
- Phase 5 can add true DAG support with parallel execution

---

## Sources

### Primary (HIGH confidence)

- **LiteLLM Documentation:** https://docs.litellm.ai/docs/ — Covers cost tracking, quota management, token usage, rate limiting, and fallback routing
- **FastAPI Documentation:** https://fastapi.tiangolo.com/ — Request validation, async patterns, dependency injection
- **Pydantic v2 Documentation:** https://docs.pydantic.dev/ — Data validation for request/plan schemas
- **SQLAlchemy 2.0 Documentation:** https://docs.sqlalchemy.org/ — ORM for agent registry and performance tracking
- **PostgreSQL 13+ Documentation:** https://www.postgresql.org/docs/ — Relational schema for agent state
- **aio-pika Documentation:** https://aio-pika.readthedocs.io/ — Async RabbitMQ client from Phase 2

### Secondary (MEDIUM confidence - verified with official sources)

- [Natural Language Processing With spaCy in Python – Real Python](https://realpython.com/natural-language-processing-spacy-python/) — NLU background; confirmed spaCy not needed for orchestrator's narrow use case
- [An Approach for Systematic Decomposition of Complex LLM Tasks](https://arxiv.org/pdf/2510.07772) — Task decomposition research; confirms LLM-based approach vs rule-based
- [ADaPT: As-Needed Decomposition and Planning with Language Models](https://aclanthology.org/2024.findings-naacl.264/) — Adaptive decomposition patterns
- [Agents At Work: The 2026 Playbook for Building Reliable Agentic Workflows](https://promptengineering.org/agents-at-work-the-2026-playbook-for-building-reliable-agentic-workflows/) — Plan-and-execute agent patterns, DAG scheduling insights
- [LiteLLM Spend Tracking](https://docs.litellm.ai/docs/proxy/cost_tracking) — Quota and cost tracking mechanisms
- [GitHub - PyExPool](https://github.com/eXascaleInfolab/PyExPool) — Resource-aware worker pool patterns

### Tertiary (LOW confidence - WebSearch only, marked for validation)

- [Optimize routing and scheduling in Python: a new open source solver](https://timefold.ai/blog/new-open-source-solver-python) — Scheduling algorithms (Timefold reference)
- [Ultimate Guide to AI Agent Routing (2026)](https://botpress.com/blog/ai-agent-routing) — Industry patterns for agent routing (not verified against official source)
- [GitHub - agentpool](https://github.com/phil65/agentpool) — YAML-based agent configuration framework (reference only)

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|------|-------|--------|
| **NLU Approach** | HIGH | LiteLLM, Claude, and Ollama are verified via official docs; LLM-based decomposition confirmed via academic research |
| **Work Plan Schema** | HIGH | Based on existing Phase 1-2 models (Task, ExecutionLog); Pydantic validation verified via official docs |
| **Agent Routing** | MEDIUM | PostgreSQL schema and SQLAlchemy patterns are standard; specific performance metrics need tuning post-implementation |
| **External AI Fallback** | HIGH | LiteLLM quota tracking verified via official docs; complexity assessment heuristic needs validation |
| **Complexity Assessment** | MEDIUM | Heuristics proposed but need real-world testing; will refine during Phase 4 execution |
| **Audit Logging** | HIGH | Pattern verified via Phase 1-2 execution_logs table; routing_decisions schema follows same pattern |
| **Testing Approach** | MEDIUM | Pytest + async mocking standard; specific test coverage targets need refinement during planning |

**Research date:** 2026-01-19
**Valid until:** 2026-02-19 (30 days; LLM routing and scheduling are stable, but complexity assessment heuristics may need tuning after execution)
