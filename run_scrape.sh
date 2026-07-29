#!/usr/bin/env bash
# Daily scrape wrapper — cron-safe (absolute paths, explicit cd, logged).
set -euo pipefail

PROJECT_DIR="/home/vitalii/job-scraper"
UV="/home/vitalii/.local/bin/uv"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

# Timestamped run; append to a dated log, and to a rolling latest.log
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
LOG="$LOG_DIR/scrape-$(date '+%Y-%m').log"

{
  echo "===== run start: $STAMP ====="
  "$UV" run job-scraper --delay 0.5
  echo "===== run end:   $(date '+%Y-%m-%d %H:%M:%S') ====="
  echo
} >> "$LOG" 2>&1
