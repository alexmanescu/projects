#!/bin/bash
# Pull latest PAE code and restart services if they're running.
# Usage: bash ~/alexmanescu/projects/PAE/scripts/pull.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "==> Pulling latest code into $REPO_DIR"
cd "$REPO_DIR"
git pull

# Restart launchd services only if they're loaded
for SERVICE in com.pae.workers com.pae.telegram; do
    if launchctl list | grep -q "$SERVICE"; then
        echo "==> Restarting $SERVICE"
        launchctl stop  "$SERVICE"
        launchctl start "$SERVICE"
    fi
done

echo "==> Done."
