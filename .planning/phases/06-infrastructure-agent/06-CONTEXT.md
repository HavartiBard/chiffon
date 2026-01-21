# Phase 6: Infrastructure Agent - Context

**Gathered:** 2026-01-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Infrastructure agent accepts deployment tasks from orchestrator (service-level intent, e.g., "Deploy Kuma"), maps them to existing Ansible playbooks in ~/CascadeProjects/homelab-infra, executes playbooks with streaming output, suggests improvements on failures, and generates playbook templates for new services. The agent abstracts playbook details from the orchestrator for extensibility.

</domain>

<decisions>
## Implementation Decisions

### Playbook Discovery & Caching
- Lazy scan: Agent discovers playbooks only on first task request (reduces startup overhead)
- Cache TTL: 1-hour expiration; rescans automatically to pick up new playbooks
- Manual refresh: Support both API endpoint (POST /refresh-playbooks) and CLI command for ad-hoc cache invalidation
- Single repository: Hard-coded to ~/CascadeProjects/homelab-infra/ansible (no multi-repo support in v1)
- Playbook validation: Full YAML parse during discovery; skip invalid files; report errors
- Hybrid indexing: Start with filename-based service detection (e.g., kuma-* → 'kuma' service); allow metadata tag override in playbook header comments
- Metadata extracted per playbook: service name, description/purpose, required variables, tags (for categorization)

### Task-to-Playbook Mapping
- Service-level intent abstraction: Orchestrator sends "Deploy Kuma" (not "run kuma-deployment.yml"); agent maps internally
- Hybrid matching strategy: Exact match → Cached previous mapping → LLM semantic inference (ranking order)
- LLM usage: Leverage available LLM (Ollama or Claude via fallback), not Claude alone; cache learned mappings to reduce LLM calls
- Multiple matches: Return all matching playbooks with confidence scores; orchestrator chooses preferred one
- No match handling: Return three options—suggest closest matches, offer template generation, or report no match; let orchestrator decide next step

### Output Streaming & Execution
- Execution model: Run playbook silently; send high-level summary only (not line-by-line streaming) to reduce message queue overhead
- Summary format: status (success/failed), duration, changed items count, key errors (structured, not raw ansible output)
- Failure handling: Immediate stop on first failure; report failure to orchestrator immediately
- Variable passing: Support all three methods—command-line --extra-vars, environment variables (CHIFFON_* prefix), temporary config files (--extra-vars @file.json); agent chooses appropriate method based on complexity

### Improvement Suggestions & Templates
- Suggestion timing: Generate suggestions only after playbook failures (reduces noise, focuses on problems)
- Suggestion categories: Detect idempotency issues (unsafe shell tasks), error handling gaps, performance inefficiencies, Ansible best practices, conformance to defined standards and consistency
- Suggestion format: Categorized list with reasoning (organized by type, not patches); explain why improvement is suggested
- Template generation: Scaffold with role structure, standard variables, best practice tasks, and documentation
- Template patterns: Follow Ansible Galaxy best practices and conventions (not custom patterns); ensures templates are recognizable and maintainable

### Enforcing Conventions & Standards
- Playbook metadata comments: Optional header in playbooks defining service name, description, variables, tags (enables flexible indexing)
- Suggestion standards check: Compare playbooks against defined standards during failure analysis (e.g., "must use service handlers", "config files should be templated")
- Template standards: Generated templates conform to homelab conventions captured in v1 playbook examples

### Service-Level Abstraction (Architectural)
- Orchestrator interface: Tasks are service-level intents ("Deploy Kuma", "Update Kuma Config"), not playbook-specific
- Internal mapping: Infrastructure agent owns playbook discovery, indexing, and selection logic
- Extensibility benefit: Allows future agent types (code agent, research agent) with same intent interface; orchestrator remains service-agnostic

### Claude's Discretion
- LLM model selection: Agent can use any available LLM (Ollama preferred, Claude fallback) for semantic matching; no hard-coded Claude dependency
- Cache eviction policy: Decide on LRU vs. time-based eviction for semantic mapping cache
- Playbook parsing depth: Decide how deep to parse playbook YAML for metadata extraction (just headers vs. full analysis)
- Error message formatting: Decide on error message clarity/verbosity in suggestions and failure reports

</decisions>

<specifics>
## Specific Ideas

- Playbook catalog API endpoint would expose discovered playbooks to orchestrator (metadata: service, description, tags), enabling transparency and debugging
- Consider storing improvement suggestions in database for auditing (what got suggested, when, for which playbook version)
- Hybrid matching memory: Store intent → playbook mappings in PostgreSQL (tagged with confidence, timestamp) so patterns are learned across sessions
- Template generation could optionally scaffold with real data from existing playbooks (roles, handlers, handlers from similar services)

</specifics>

<deferred>
## Deferred Ideas

- Multi-repository support (multiple playbook sources) — future extensibility, v1 uses single repo only
- Playbook versioning and history tracking — add to backlog for audit trail improvements
- Automated playbook updates/patches based on suggestions — v2 feature; v1 generates suggestions only
- Integration with Ansible Galaxy or public playbook repositories — out of scope for v1 homelab-focused agent

</deferred>

---

*Phase: 06-infrastructure-agent*
*Context gathered: 2026-01-21*
