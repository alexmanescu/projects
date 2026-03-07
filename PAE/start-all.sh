#!/bin/bash
# Start both PAE workers and Telegram bot in the background.
# Usage: bash ~/alexmanescu/projects/PAE/start-all.sh
#
# Logs go to logs/workers.log and logs/bot.log.
# Use 'kill $(cat logs/workers.pid) $(cat logs/bot.pid)' to stop both.

PAE_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PAE_DIR/venv/bin/activate"
LOG_DIR="$PAE_DIR/logs"

if [ ! -f "$VENV" ]; then
    echo "ERROR: venv not found at $PAE_DIR/venv"
    echo "Run: cd $PAE_DIR && python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

mkdir -p "$LOG_DIR"
source "$VENV"
cd "$PAE_DIR"

# ── Start workers ────────────────────────────────────────────────────────────
echo "==> Starting PAE workers (logging to $LOG_DIR/workers.log)"
nohup python scripts/run_workers.py >> "$LOG_DIR/workers.log" 2>&1 &
echo $! > "$LOG_DIR/workers.pid"
echo "    PID $(cat "$LOG_DIR/workers.pid")"

# ── Start Telegram bot ──────────────────────────────────────────────────────
echo "==> Starting PAE Telegram bot (logging to $LOG_DIR/bot.log)"
nohup python scripts/run_telegram_bot.py >> "$LOG_DIR/bot.log" 2>&1 &
echo $! > "$LOG_DIR/bot.pid"
echo "    PID $(cat "$LOG_DIR/bot.pid")"

echo ""
echo "Both processes running in background."
echo "  Tail logs:  tail -f $LOG_DIR/workers.log $LOG_DIR/bot.log"
echo "  Stop both:  kill \$(cat $LOG_DIR/workers.pid) \$(cat $LOG_DIR/bot.pid)"
