#!/usr/bin/env bash
# Supervisor script — restarts the bot automatically if it crashes.
# Designed for 10+ day uninterrupted operation.
#
# Usage:
#   ./run.sh                  # Run in foreground
#   nohup ./run.sh &          # Run in background (survives terminal close)
#   nohup ./run.sh >> bot_output.log 2>&1 &   # Background with log capture

set -euo pipefail

MAX_RESTART_DELAY=300   # Max 5 minutes between restarts
RESTART_DELAY=5         # Start at 5 seconds

cd "$(dirname "$0")"

echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Bot supervisor started."
echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Strategy: $(python3 -c 'import json; print(json.load(open("state/selected_strategy.json"))["selected_strategy"])' 2>/dev/null || echo 'default')"

while true; do
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Starting bot process..."

    if python3 bot.py; then
        # Clean exit (SIGINT/SIGTERM) — don't restart
        echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Bot exited cleanly. Stopping supervisor."
        exit 0
    fi

    EXIT_CODE=$?
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Bot crashed with exit code $EXIT_CODE."
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Restarting in ${RESTART_DELAY}s..."
    sleep "$RESTART_DELAY"

    # Exponential backoff capped at MAX_RESTART_DELAY
    RESTART_DELAY=$((RESTART_DELAY * 2))
    if [ "$RESTART_DELAY" -gt "$MAX_RESTART_DELAY" ]; then
        RESTART_DELAY=$MAX_RESTART_DELAY
    fi
done
