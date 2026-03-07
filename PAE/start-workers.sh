#!/bin/bash
# Start the PAE scheduled workers (scrape + detect + monitor on a loop).
# Usage: bash ~/alexmanescu/projects/PAE/start-workers.sh
#
# This runs APScheduler with 5 recurring jobs:
#   scrape_news (60m), detect_confluence (30m), monitor_positions (15m),
#   check_stops (5m), update_prices (1m)
#
# Run start-bot.sh in a separate terminal for the Telegram bot.

PAE_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PAE_DIR/venv/bin/activate"

if [ ! -f "$VENV" ]; then
    echo "ERROR: venv not found at $PAE_DIR/venv"
    echo "Run: cd $PAE_DIR && python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

echo "==> Activating venv"
source "$VENV"

echo "==> Starting PAE scheduled workers"
cd "$PAE_DIR"
python scripts/run_workers.py
