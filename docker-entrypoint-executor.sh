#!/bin/bash
set -e

# Logging helper
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

# Validate required environment variables
if [ -z "$CHIFFON_EXECUTOR_TOKEN" ]; then
    log "ERROR: CHIFFON_EXECUTOR_TOKEN is not set"
    exit 1
fi

if [ -z "$PROJECT" ]; then
    log "ERROR: PROJECT is not set (e.g., orchestrator-core)"
    exit 1
fi

# Set defaults
REPO_PATH="${REPO_PATH:-.}"
QUEUE_PATH="${QUEUE_PATH:-$REPO_PATH/tasks/queue}"
CRON_SCHEDULE="${CRON_SCHEDULE:-*/30 * * * *}"
EXECUTION_MODE="${EXECUTION_MODE:-cron}"
GITEA_BASE_URL="${GITEA_BASE_URL:-https://code.klsll.com}"
LMSTUDIO_URL="${LMSTUDIO_URL:-http://spraycheese.lab.klsll.com:1234}"

log "Starting chiffon executor"
log "  Project:  $PROJECT"
log "  Repo:     $REPO_PATH"
log "  Queue:    $QUEUE_PATH"
log "  LLM:      $LMSTUDIO_URL"
log "  Mode:     $EXECUTION_MODE"
log "  Schedule: $CRON_SCHEDULE"

# Verify git repository is accessible at REPO_PATH
if ! git -C "$REPO_PATH" status > /dev/null 2>&1; then
    log "ERROR: Cannot access git repository at $REPO_PATH"
    exit 1
fi
log "Git repository accessible at $REPO_PATH"

# Mode: adhoc — run once and exit
if [ "$EXECUTION_MODE" = "adhoc" ]; then
    log "Running in adhoc mode (execute once, then exit)"
    /app/.venv/bin/python3 -m chiffon.cli run-once --project "$PROJECT" --use-llm
    exit $?
fi

# Mode: cron — install cron job and start daemon in foreground
log "Running in cron mode (schedule: $CRON_SCHEDULE)"

CRON_JOB="$CRON_SCHEDULE /app/.venv/bin/python3 -m chiffon.cli run-once --project $PROJECT --use-llm >> /var/log/chiffon-cron.log 2>&1"

# Install cron job for root
echo "$CRON_JOB" | crontab -
log "Cron job installed: $CRON_JOB"

# Start cron in foreground, bridging log file to stdout for docker logs
log "Starting cron daemon"
touch /var/log/chiffon-cron.log
tail -f /var/log/chiffon-cron.log &
exec cron -f
