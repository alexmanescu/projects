#!/bin/bash
# Start the PAE Telegram bot listener.
# Usage: bash ~/alexmanescu/projects/PAE/start-bot.sh
#
# The bot handles /pause, /resume, /wstatus commands and trade approvals.
# Run in a separate terminal alongside start-workers.sh.

PAE_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PAE_DIR/venv/bin/activate"

if [ ! -f "$VENV" ]; then
    echo "ERROR: venv not found at $PAE_DIR/venv"
    echo "Run: cd $PAE_DIR && python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

echo "==> Activating venv"
source "$VENV"

echo "==> Starting PAE Telegram bot listener"
cd "$PAE_DIR"
python scripts/run_telegram_bot.py
