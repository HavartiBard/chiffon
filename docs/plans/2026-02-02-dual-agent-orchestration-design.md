# Dual-Agent Orchestration Design
**Date:** 2026-02-02
**Scope:** Bootstrap the dual-agent model with pull-based task materialization, file queue, and Gitea Projects

---

## Overview

Establish a minimal viable dual-agent loop:
- **Claude (cloud):** Master orchestrator—reads Gitea issues, materializes task YAMLs
- **Local LLM (OpenCode):** Executor—consumes from file queue, runs bounded steps, pushes artifacts
- **Gitea Projects:** Organize work by milestone
- **File queue:** Source of truth for execution

**Token conservation strategy:** You stay in planning/validation; local LLM handles deterministic execution.

---

## Architecture

### System Components

```
Gitea Projects (visibility/coordination)
         ↓
    Claude (me) - read issue, parse intent
         ↓
File queue: tasks/queue/<project>/*.yaml (execution interface)
         ↓
Local LLM - consume, execute, report
         ↓
Artifacts: branches, PRs, run reports
```

### Gitea Projects (Work Queues)

Five projects organize the Chiffon roadmap:

1. **`orchestrator-core`** — MRL0 (Minimum Runnable Loop, local)
2. **`guardrails`** — Policy & Guardrails (unattended safety)
3. **`gitea-workflow`** — Gitea Loop (issues → PRs)
4. **`local-delegation`** — Local-first LLM delegation
5. **`unattended-runner`** — Night Runner (async execution)

Each project has an issue board. Issues tagged `chiffon:queue` become tasks.

### File Queue Structure

```
tasks/queue/
├── orchestrator-core/
│   ├── task-1.yaml
│   ├── task-2.yaml
│   └── ...
├── guardrails/
├── gitea-workflow/
├── local-delegation/
└── unattended-runner/

tasks/runs/
├── task-1/
│   ├── report.md
│   ├── branch-name.txt
│   └── run.log
└── ...
```

---

## Workflow

### Task Lifecycle

1. **Issue creation (you):** Create a Gitea issue in a project with clear goal, file ops, verify commands
2. **Task materialization (Claude):** You ask "pick up issue #X from orchestrator-core" → I fetch, parse, write task YAML
3. **Execution (local LLM):** Run `chiffon run-once --project orchestrator-core` → consume task, execute steps
4. **Artifacts:** Branch created, commits pushed, run report written
5. **Review (you):** Inspect PR, close issue or ask for refinement

### Trigger Model (Pull-based)

- **You initiate:** Ask me to pick up a specific issue
- **I materialize:** Create the task YAML, show you for review
- **You approve:** Commit to queue and run executor
- **Future (Chiffon listens):** Eventually Chiffon monitors Gitea directly and auto-materializes

---

## Task YAML Schema

**File:** `tasks/queue/<project>/task-<id>.yaml`

```yaml
version: "1"
metadata:
  id: "task-123"
  source: "gitea:orchestrator-core:42"  # project:issue_id
  created_by: "claude"
  created_at: "2026-02-02T10:00:00Z"
  priority: 1  # 1=critical, 2=high, 3=normal, 4=low

complexity:
  estimated_tokens: 2000
  estimated_steps: 3
  estimated_lines_of_diff: 150
  tier: "simple"  # trivial | simple | moderate | complex
  required_capabilities:
    - "python-edit"
    - "pytest"
  estimated_duration_seconds: 60

dependencies:
  requires_completed:
    - "task-122"
    - "task-120"
  blocks:
    - "task-124"

goal: |
  Clear, bounded statement of what to accomplish.

scope:
  allowed_write_globs:
    - "src/chiffon/cli/*.py"
    - "src/chiffon/orchestrator/*.py"
  allowed_read_globs:
    - "src/**"
    - "tasks/queue/**"
    - "tasks/runs/**"

constraints:
  max_files_changed: 10
  max_diff_bytes: 50000
  timeout_seconds: 300
  denylisted_commands:
    - "rm -rf"
    - "git push.*--force"

steps:
  - id: "step-1"
    action: "edit"
    file: "src/chiffon/cli/main.py"
    instructions: |
      Precise, unambiguous instructions.

  - id: "step-2"
    action: "run"
    command: "pytest tests/ -v"
    description: "Why we're running this"

verify:
  - "pytest tests/ -v | grep -q 'passed'"
  - "python -m chiffon run-once --help | grep -q 'project'"

assumptions:
  - "tests/ exists and is runnable"
  - "src/chiffon/cli/main.py is the entry point"
```

### Schema Fields

| Field | Purpose | Notes |
|-------|---------|-------|
| `metadata.priority` | Task selection order | 1=critical, 4=low. Within project, sort by priority then created_at |
| `complexity.tier` | Route to capable agents | trivial, simple, moderate, complex |
| `complexity.required_capabilities` | Hint for agent selection | e.g., "python-edit", "system-admin" |
| `dependencies.requires_completed` | Gating | Executor waits or rejects if dependencies incomplete |
| `dependencies.blocks` | Forward visibility | Other tasks know they're gated by this one |
| `scope.allowed_*_globs` | Policy enforcement | Fail-closed: only allow writes within these paths |
| `constraints` | Safety bounds | Timeouts, max diff, denylisted patterns |
| `steps` | Atomic, ordered actions | edit, run, create. Labeled for auditability |
| `verify` | Acceptance criteria | Shell-compatible commands executor can run |
| `assumptions` | Intent documentation | Help catch mismatches with executor |

---

## Division of Labor

### Claude (Master Orchestrator)
- Read Gitea issues tagged `chiffon:queue`
- Parse goal, constraints, scope
- Materialize task YAML (goal, steps, policy)
- Break ambiguous issues into sub-tasks if needed
- Read run reports, summarize findings in Gitea comments
- Flag policy violations or execution errors

### Local LLM (Executor)
- Poll `tasks/queue/<project>/` in priority order
- Check dependencies: skip if `requires_completed` incomplete
- Execute steps atomically
- Run verify commands
- Create branch, push commits
- Write run report with inputs, outputs, diffs, commands, results
- Never execute denylisted commands
- Respect all constraints (timeouts, max diff, max files)

### You (Decision Maker)
- Create issues in Gitea with clear requirements
- Ask me to materialize tasks
- Review task YAML before running (optional)
- Inspect PRs and run reports
- Merge PRs or ask for refinement
- Manage Gitea project boards for visibility

---

## First Run (MRL0)

### Setup
1. Create Gitea Project `orchestrator-core`
2. Create an issue: "Implement CLI: chiffon run-once"
3. Tag it `chiffon:queue`

### You ask me to materialize
```
"Pick up orchestrator-core issue #1 and materialize it"
```

### I create
```
tasks/queue/orchestrator-core/task-1.yaml
```

### You review and commit
```bash
git add tasks/queue/
git commit -m "queue: task-1 (orchestrator-core issue #1)"
```

### Local LLM runs
```bash
chiffon run-once --project orchestrator-core --repo /path/to/chiffon
```

### Executor
- Reads `tasks/queue/orchestrator-core/task-1.yaml`
- Executes steps, creates branch, pushes commits
- Writes `tasks/runs/task-1/report.md`

### You review
- Inspect PR in Gitea
- I read report, comment summary on issue
- You approve/merge or ask for fixes

---

## Safety & Auditability

### Fail-Closed
- Only write to `allowed_write_globs` paths
- Only run commands not in `denylisted_commands`
- Reject if diff exceeds `max_diff_bytes` or `max_files_changed`
- Stop on timeout or verification failure

### Audit Trail
Each run produces `tasks/runs/<task-id>/`:
- `report.md` — human-readable summary (inputs, outputs, status)
- `branch-name.txt` — which branch was created
- `run.log` — full execution transcript
- Committed diffs on the branch itself

### Error Recovery
- If step fails, executor stops and reports why
- You decide: retry with modified task, or escalate
- No infinite loops; bounded retries per task

---

## Future Evolution

### Phase 2: Push-based (Chiffon listens)
- Chiffon monitors Gitea for `chiffon:queue` issues
- Auto-materializes task YAMLs
- Claude still validates/shapes tasks, but more automated

### Phase 3: RabbitMQ
- Replace file queue with message broker
- Multiple executors can consume in parallel
- Better scalability for multi-agent runs

### Phase 4: Night Runner
- Unattended execution with configurable limits
- Systemd timer / cron integration
- Daily summary reports

---

## Implementation Checklist

- [ ] Create Gitea Projects (orchestrator-core, guardrails, gitea-workflow, local-delegation, unattended-runner)
- [ ] Scaffold `tasks/queue/<project>/` and `tasks/runs/` directories
- [ ] Implement task YAML parsing in Chiffon (loader, validator)
- [ ] Implement `chiffon run-once --project <name>` CLI entry point
- [ ] Implement executor: step runner, constraints checker, report writer
- [ ] Add Gitea issue reader (fetch, parse, materialize task YAML)
- [ ] Wire up artifact capture (branch name, logs, diffs)
- [ ] Add run report generator (markdown format)
- [ ] Test end-to-end: issue → task → execution → PR → report
