-- PostgreSQL Post-Mortem Query Examples
--
-- Run these queries against the agent_deploy database to analyze execution history,
-- debug failures, and understand system performance.
--
-- Connection: psql -U agent -d agent_deploy
-- Or: docker-compose exec postgres psql -U agent -d agent_deploy


-- Query 1: All failed tasks in the last 7 days
-- Use case: Identify recent failures for debugging
SELECT task_id, request_text, status, error_message, created_at, approved_at, completed_at
FROM tasks
WHERE status = 'failed' AND created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;


-- Query 2: Execution timeline for a specific task
-- Use case: Debug why a task took too long or failed
-- Replace 'XXX-XXX-XXX-XXX' with actual task_id
SELECT
    task_id,
    step_number,
    agent_type,
    action,
    status,
    duration_ms,
    timestamp,
    output_summary
FROM execution_logs
WHERE task_id = 'XXX-XXX-XXX-XXX'
ORDER BY step_number ASC;


-- Query 3: Total resources used by tasks (last 30 days)
-- Use case: Track resource consumption trends
SELECT
    task_id,
    request_text,
    (actual_resources->>'duration_seconds')::int as duration_sec,
    (actual_resources->>'gpu_vram_mb_used')::int as gpu_mb,
    (actual_resources->>'cpu_time_ms')::int as cpu_ms,
    created_at
FROM tasks
WHERE created_at > NOW() - INTERVAL '30 days' AND status = 'completed'
ORDER BY created_at DESC;


-- Query 4: Tasks using external AI and their costs
-- Use case: Monitor AI cost spending
SELECT
    task_id,
    request_text,
    status,
    external_ai_used->>'model' as ai_model,
    (external_ai_used->>'token_count')::int as tokens,
    (external_ai_used->>'cost_usd')::numeric as cost_usd,
    created_at
FROM tasks
WHERE external_ai_used IS NOT NULL
ORDER BY created_at DESC;


-- Query 5: Average execution metrics by agent type
-- Use case: Understand which agents are bottlenecks
SELECT
    agent_type,
    COUNT(*) as execution_count,
    AVG(duration_ms)::integer as avg_duration_ms,
    MIN(duration_ms) as min_duration_ms,
    MAX(duration_ms) as max_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_ms
FROM execution_logs
GROUP BY agent_type
ORDER BY avg_duration_ms DESC;


-- Query 6: Failed steps (errors during execution)
-- Use case: Identify where tasks fail
SELECT
    task_id,
    step_number,
    agent_type,
    action,
    status,
    output_summary,
    timestamp
FROM execution_logs
WHERE status = 'failed'
ORDER BY timestamp DESC;


-- Query 7: Tasks by status (current state)
-- Use case: Get overview of system state
SELECT
    status,
    COUNT(*) as count,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as last_24h,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as last_7d
FROM tasks
GROUP BY status
ORDER BY count DESC;


-- Query 8: Total AI cost per model (all time)
-- Use case: Budget tracking
SELECT
    external_ai_used->>'model' as model,
    COUNT(*) as usage_count,
    SUM((external_ai_used->>'token_count')::int) as total_tokens,
    SUM((external_ai_used->>'cost_usd')::numeric) as total_cost_usd
FROM tasks
WHERE external_ai_used IS NOT NULL
GROUP BY external_ai_used->>'model'
ORDER BY total_cost_usd DESC;


-- Query 9: Longest running tasks (last 30 days)
-- Use case: Find performance issues
SELECT
    task_id,
    request_text,
    status,
    created_at,
    (actual_resources->>'duration_seconds')::int as duration_sec,
    (actual_resources->>'gpu_vram_mb_used')::int as gpu_mb
FROM tasks
WHERE created_at > NOW() - INTERVAL '30 days'
ORDER BY (actual_resources->>'duration_seconds')::int DESC NULLS LAST
LIMIT 10;


-- Query 10: Task success rate by day
-- Use case: Track reliability trends
SELECT
    DATE(created_at) as day,
    COUNT(*) as total_tasks,
    COUNT(*) FILTER (WHERE status = 'completed') as completed,
    COUNT(*) FILTER (WHERE status = 'failed') as failed,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'completed') / COUNT(*),
        2
    ) as success_rate_pct
FROM tasks
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at)
ORDER BY day DESC;
