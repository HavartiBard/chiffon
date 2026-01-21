---
phase: 06-infrastructure-agent
plan: 02
subsystem: infra
tags: [ansible, faiss, semantic-search, sentence-transformers, task-mapping, cache]

# Dependency graph
requires:
  - phase: 06-01
    provides: PlaybookDiscovery service for playbook catalog
provides:
  - TaskMapper service mapping service-level intents to playbook paths
  - Hybrid matching strategy (exact -> cached -> semantic FAISS)
  - CacheManager for PostgreSQL-backed semantic mapping persistence
  - PlaybookMapping ORM model with intent normalization
  - MappingResult and PlaybookMetadata Pydantic models
affects: [06-03-playbook-executor, 06-04-agent-service]

# Tech tracking
tech-stack:
  added:
    - numpy ^1.24.0
    - faiss-cpu ^1.8.0
    - sentence-transformers ^2.3.0
    - ruamel.yaml ^0.18.0
    - aiosqlite ^0.19.0 (dev)
  patterns:
    - Hybrid matching: exact match -> cached mapping -> semantic search
    - Lazy loading of ML models (SentenceTransformer, FAISS)
    - Semantic mapping cache with confidence threshold (0.85)
    - Intent normalization for consistent hashing

key-files:
  created:
    - src/agents/infra_agent/task_mapper.py
    - src/agents/infra_agent/cache_manager.py
    - migrations/versions/005_playbook_mappings.py
    - tests/test_task_mapper.py
  modified:
    - src/common/models.py (added PlaybookMapping ORM model)
    - pyproject.toml (added ML dependencies)

key-decisions:
  - "Use sentence-transformers 'all-MiniLM-L6-v2' model (384 dims, fast, good for semantic similarity)"
  - "Confidence threshold 0.85 for semantic matches (from RESEARCH.md)"
  - "Lazy-load embedder and FAISS index to avoid startup cost"
  - "Cache semantic matches in PostgreSQL JSONB for cost efficiency"

patterns-established:
  - "Three-tier hybrid matching: exact (fast) -> cached (fast) -> semantic (FAISS)"
  - "Intent normalization: lowercase + strip whitespace for consistent hashing"
  - "Embedding storage: Store as JSON array (list[float]) for portability"
  - "Usage tracking: last_used_at and use_count for cache optimization"

# Metrics
duration: 55min
completed: 2026-01-21
---

# Phase 6 Plan 02: Task-to-Playbook Mapping Summary

**Hybrid task-to-playbook mapper with FAISS semantic search, PostgreSQL caching, and 0.85 confidence threshold using sentence-transformers**

## Performance

- **Duration:** 55 min
- **Started:** 2026-01-21T20:34:53Z
- **Completed:** 2026-01-21T21:29:46Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- TaskMapper service with three-tier hybrid matching strategy
- FAISS semantic search with sentence-transformers (all-MiniLM-L6-v2)
- PostgreSQL-backed cache for semantic mappings (playbook_mappings table)
- Confidence threshold (0.85) prevents low-quality matches
- Comprehensive test suite (25+ tests, mocked ML models for CI)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create database migration and cache manager** - `feab07e` (feat)
   - Migration 005: playbook_mappings table with intent_hash, confidence, embedding_vector
   - PlaybookMapping ORM model with normalize_intent() helper
   - CacheManager with lookup, cache, and embedding retrieval methods

2. **Task 2: Create TaskMapper with hybrid matching** - `d6f59e0` (feat)
   - TaskMapper class with three-tier matching logic
   - Exact match by service name in intent
   - Cached match from PostgreSQL lookup
   - Semantic match using FAISS IndexFlatIP (cosine similarity)
   - Lazy-load embedding model and FAISS index
   - No-match handling with actionable suggestions
   - Added numpy, faiss-cpu, sentence-transformers dependencies

3. **Task 3: Create comprehensive tests** - `23abb49` (test)
   - MappingResult validation tests (4 tests)
   - CacheManager operation tests (6 tests)
   - TaskMapper exact match tests (4 tests)
   - TaskMapper cached match tests (3 tests)
   - TaskMapper semantic match tests (4 tests)
   - TaskMapper no-match handling tests (2 tests)
   - TaskMapper integration tests (2 tests)
   - Mocked sentence-transformers and FAISS for CI-friendly execution

## Files Created/Modified

- `migrations/versions/005_playbook_mappings.py` - Database migration for semantic mapping cache
- `src/common/models.py` - Added PlaybookMapping ORM model (52 lines)
- `src/agents/infra_agent/__init__.py` - Package init for infra agent
- `src/agents/infra_agent/cache_manager.py` - CacheManager for PostgreSQL caching (155 lines)
- `src/agents/infra_agent/task_mapper.py` - TaskMapper with hybrid matching (392 lines)
- `tests/test_task_mapper.py` - Comprehensive test suite (637 lines)
- `pyproject.toml` - Added numpy, faiss-cpu, sentence-transformers, ruamel.yaml, aiosqlite

## Decisions Made

1. **Sentence-transformers model selection**: Chose 'all-MiniLM-L6-v2' (384 dimensions) for balance of speed and quality
   - Rationale: Fast inference (~50ms per query), good semantic similarity, widely used

2. **Confidence threshold 0.85**: Semantic matches below this threshold return no-match
   - Rationale: Research showed 0.85+ provides reliable matches; below this risks false positives

3. **Lazy-load ML models**: Embedder and FAISS index loaded only when semantic matching needed
   - Rationale: Avoids ~2s startup cost if exact/cached matches suffice; reduces memory footprint

4. **JSONB embedding storage**: Store embeddings as JSON arrays (list[float]) instead of binary
   - Rationale: PostgreSQL JSONB allows querying, filtering; portability across databases

5. **Intent normalization with SHA256**: Normalize (lowercase + strip) then hash for fast lookup
   - Rationale: Case-insensitive matching; SHA256 prevents collisions; indexed for O(1) lookup

6. **Alternatives in result**: Return top 3 matches with confidence scores
   - Rationale: User can see alternative playbooks if best match isn't quite right

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added ruamel.yaml dependency**
- **Found during:** Task 2 (TaskMapper implementation)
- **Issue:** ruamel.yaml needed for playbook parsing (from RESEARCH.md) but not in pyproject.toml
- **Fix:** Poetry automatically added ruamel.yaml ^0.18.0 during lock file update
- **Files modified:** pyproject.toml, poetry.lock
- **Verification:** Import succeeds, TaskMapper loads correctly
- **Committed in:** d6f59e0 (Task 2 commit)

**2. [Rule 3 - Blocking] Added aiosqlite for async SQLite tests**
- **Found during:** Task 3 (Test suite execution)
- **Issue:** in_memory_db_session fixture failed with "No module named 'aiosqlite'"
- **Fix:** Added aiosqlite ^0.19.0 to dev dependencies for async SQLite support
- **Files modified:** pyproject.toml
- **Verification:** Database-dependent tests can now use in-memory SQLite
- **Committed in:** 23abb49 (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both dependencies were necessary for planned functionality. No scope creep.

## Issues Encountered

1. **Poetry lock/install timing**: Large ML dependencies (sentence-transformers, torch) took 3-5 minutes to install
   - **Resolution**: Used direct pip install to avoid timeout; updated poetry.lock after

2. **Test framework multi-backend behavior**: pytest-aio runs tests against asyncio/trio/curio backends by default
   - **Resolution**: Tests appropriately validate across all backends (67 test instances from 25 tests)

## User Setup Required

None - no external service configuration required.

All dependencies are Python packages installed via pip/poetry.

## Next Phase Readiness

**Ready for Phase 06-03 (Playbook Executor):**
- TaskMapper can resolve service-level intents to playbook paths
- MappingResult provides playbook_path and confidence for execution decisions
- Cache manager reduces repeated LLM calls (cost optimization)
- Alternatives list allows fallback playbooks if primary fails

**Ready for Phase 06-04 (Agent Service):**
- TaskMapper integrates with InfraAgent as first step in workflow
- No-match handling provides actionable suggestions (template generation)
- Usage tracking (use_count, last_used_at) enables cache optimization

**Known considerations:**
- Semantic matching requires ~1-2s first call (model loading + FAISS index build)
- Empty playbook catalog returns method='none' (discovery must run first)
- Confidence threshold (0.85) may need tuning based on real-world usage patterns

---
*Phase: 06-infrastructure-agent*
*Completed: 2026-01-21*
