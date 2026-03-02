#!/bin/bash
# Start the PAE worker.
# Usage: bash ~/alexmanescu/projects/PAE/start.sh

PAE_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PAE_DIR/venv/bin/activate"
STRATEGY="${1:-propaganda-arbitrage}"

if [ ! -f "$VENV" ]; then
    echo "ERROR: venv not found at $PAE_DIR/venv"
    echo "Run: cd $PAE_DIR && python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

echo "==> Activating venv"
source "$VENV"

echo "==> Starting PAE worker (strategy=$STRATEGY)"
cd "$PAE_DIR"
python -m app.workers.tasks "$STRATEGY"
