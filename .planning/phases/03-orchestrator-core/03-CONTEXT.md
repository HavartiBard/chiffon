# Phase 3: Orchestrator Core - Context

**Gathered:** 2026-01-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Orchestrator accepts natural language requests, structures them into executable work plans, routes to appropriate agents based on resource availability and capability, and falls back to external AI (Claude) when local reasoning is insufficient. Covers request parsing, plan generation, agent routing, and AI fallback logic.

</domain>

<decisions>
## Implementation Decisions

### Request Parsing & Intent Extraction

#### Automatic Sub-task Decomposition
- Orchestrator automatically decomposes complex requests into sub-tasks (e.g., "Deploy Kuma and configure" → deployment task + config task)
- Multi-step requests broken down without requiring user confirmation of breakdown
- Enables autonomous orchestration while maintaining auditability

#### Ambiguity Handling
- For vague/ambiguous requests, orchestrator makes best guess and presents assumed breakdown to user for approval
- If user rejects plan, orchestrator can revise
- Balances autonomy with safety (user approves before execution)

#### Out-of-Scope Request Handling
- When request cannot be mapped to known agents/capabilities:
  - Inform user: "I don't have capability for [X]; logged for review"
  - Automatic logging to post-mortem queue for feature gap analysis
  - If request is frequently asked or user-initiated gap review: ask "Log this as feature request for architect agent?"
  - Heuristic: high-frequency gaps → ask user; rare gaps → auto-log silently

#### Request Tracking
- Assign tracking ID after orchestrator decides to process (not on receipt)
- Only track actionable requests; cleaner audit trail, less noise

#### Request Shortcuts & Templates
- Support both request templates (e.g., "kuma-deploy") and free-form natural language
- Templates provide quick execution paths; natural language for flexibility
- User chooses convenience level per interaction

#### Proactive Suggestions
- Orchestrator should proactively suggest actions based on system state (e.g., "Kuma is out of date; want me to check for updates?")
- Enables autonomous oversight; builds on orchestrator's role as system coordinator

#### Explanation Verbosity
- User can toggle between "explain all decisions" and "explanation only for risky/unusual decisions"
- Per-interaction control; respects user preference for verbosity

### Work Plan Structure & Ordering

#### Plan Presentation Format
- Present plans as sequential numbered list (1) → 2) → 3))
- Clear, linear, easy to understand
- User reads plan in <1 minute

#### Resource Requirements in Plans
- Show resource requirements for each step ("Step 1 needs 4GB GPU")
- Reorder steps based on resource availability: run low-resource steps while waiting for GPU availability
- Enables intelligent scheduling and prevents blocking on unavailable resources

#### Handling Unavailable Resources
- If required resource unavailable (all GPUs at capacity):
  - Suggest alternatives: a) Run on CPU (slower), b) Pause and resume later, c) Reschedule for [time]
  - Give user choice; prevents artificial blocking while respecting resource constraints

#### Estimates & Costs (Hidden from User)
- Orchestrator tracks duration/cost estimates internally
- Do NOT show estimates to user in plan presentation
- Simplifies UX; orchestrator handles cost optimization transparently

### Agent Routing Logic

#### Agent Pool Assignment
- Route work by agent type → agent pool (all infra tasks → infra pool)
- Within pool, route to best available agent
- Enables scalability; pools handle capacity; individual routing optimizes quality

#### Offline Agent Pool Handling
- If target agent pool is offline/empty: notify user immediately
- "Infra agent pool offline. Cannot proceed without manual override."
- User can then decide: wait, retry, or acknowledge risk

#### Performance-Based Routing
- Track agent performance (success rate, avg duration)
- Route to agents with higher success rates; learn which agents most reliable
- Over time, improves outcomes

#### Failure Re-routing
- On task failure: automatically retry on different agent (max 3 retries)
- Handles transient agent failures without user intervention
- Improves resilience

#### Task Dependency & Context
- Consider task dependencies when routing: prefer agents that recently completed related tasks
- Provides context/warm state for follow-up work
- Improves speed and reduces re-learning overhead

#### Agent Difficulty Assessment
- Agents report difficulty/complexity assessment after task completion ("straightforward" vs "tricky")
- Orchestrator uses assessment to adjust routing for future similar tasks
- Over time, improves task-agent matching

#### Expert Mode Agent Pinning
- Automatic routing by default
- Expert users can pin work to specific agents if needed ("Always use Agent-GPU-02 for my GPU tasks")
- Respects user expertise while defaulting to automatic

#### Manual Agent Specialization
- Administrator can tag agents with skills/specializations (e.g., "Agent-A: config specialist", "Agent-B: deployment specialist")
- Orchestrator routes tasks to specialized agents when available
- Explicit; no learning required; deterministic

#### Routing Audit Trail
- Every routing decision fully logged and explainable
- Shows in audit: "Route to Agent-A (success rate 95%, specialization: config)"
- Supports post-mortem analysis and transparency

#### Load Balancing
- Claude's Discretion: weighted vs round-robin load balancing
- Can use either approach; weighted is more sophisticated, round-robin more predictable
- Decision can evolve as system scales

### External AI Fallback Triggers

#### Fallback Decision Criteria
- Use complexity + quota-based assessment (not quota alone)
- Pre-assess task complexity upfront (before routing)
- Complexity threshold: high-complexity tasks call Claude regardless of quota
- Quota threshold: if <20% remaining calls, prefer Claude to preserve local quota
- Combines cost awareness (quota) with quality awareness (complexity)

#### Fallback Transparency
- Fallback handled silently; no notifications to user
- Reduces UI noise; orchestrator manages transparently
- Logged in audit trail for post-mortem analysis

#### Quota Exhaustion (No Fallback Available)
- If Claude quota exhausted AND local LLM can't handle task:
  - Pause execution
  - Wait for quota refresh
  - Notify user of pause reason + estimated wait time
  - User can choose to accept pause or retry with simpler approach

#### Claude Call Batching
- Batch multiple tasks and call Claude once with all context
- More cost-efficient than per-task calls
- Orchestrator groups logically related tasks for single Claude invocation

#### Fallback Audit Logging
- Every fallback decision logged in audit trail
- Task record includes: "Reasoning: Claude" or "Reasoning: Ollama"
- Enables review of which decisions used which LLM
- Supports cost analysis and pattern detection

#### Claude Failure Fallback
- If Claude call fails (timeout, rate limit, error): fallback to Ollama
- If both fail: execution stops
- Improves resilience without losing cost discipline

#### Fallback Pattern Learning
- Track which task types consistently fail with Ollama
- Over time, optimize routing: high-failure task types → prefer Claude
- Learns patterns to reduce unnecessary retries

#### Fallback Policy Overrides
- Support user-configurable fallback policies ("Always use Claude for planning", "Use Ollama for routine tasks")
- Allows power users to set preferences based on their cost/quality tradeoffs
- Default: automatic decision-making

### Claude's Discretion

- Confidence threshold for local LLM (>85% confidence before using vs always try local first) — both approaches valid; pick based on cost vs accuracy preference
- Implementation of batching heuristic (how to group tasks) — can use simple or sophisticated grouping
- Exact "high-complexity" thresholds — define during implementation based on task taxonomy

</decisions>

<specifics>
## Specific Ideas

- Core use case: User says "Deploy Kuma Uptime and add our existing portals to config" → orchestrator should parse that as 2 tasks, create a plan, present it, execute serially
- Orchestrator should feel like a proactive assistant: monitoring system health, suggesting improvements, learning from patterns
- Audit trail should answer "Why did orchestrator do X?" at every decision point
- Cost awareness is critical but should not appear in user-facing UX; optimization happens behind the scenes

</specifics>

<deferred>
## Deferred Ideas

- Advanced scheduling (pause/resume based on resource metrics) — belongs in Phase 5 (State & Audit Integration)
- Architect agent for reviewing feature gaps — belongs in v2 roadmap (post-mortem agent + planning improvements)
- Complex dependency graphs (DAGs with parallel branches) — v2 feature; Phase 3 focuses on linear workflows
- Local LLM optimization (training/fine-tuning) — infrastructure improvement; not v1 scope

</deferred>

---

*Phase: 03-orchestrator-core*
*Context gathered: 2026-01-19*
