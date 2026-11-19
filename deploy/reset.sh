#!/usr/bin/env bash
# Full game reset from the host laptop: stop, back up, (optionally pull), wipe DB, re-seed, start.
# Usage: deploy/reset.sh [--pull] [--yes]
#   --pull  git pull + pip install -e before re-seeding (new code / steps / teams)
#   --yes   no confirmation prompt
# Re-seeding reloads content/*.yaml, so team names, steps and challenges come back fresh.
# Edit .env first if needed; it is re-read on start. Run as the service user (uses sudo for systemctl).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/graduapp}"
SERVICE="${SERVICE:-graduapp}"
PULL=0; YES=0
for a in "$@"; do
  case "$a" in
    --pull) PULL=1 ;;
    --pip) PIP=1 ;; 
    --yes) YES=1 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

cd "$APP_DIR"
if [ "$YES" -ne 1 ]; then
  read -r -p "Erase ALL game state (team names, progress, events) and restart $SERVICE? [y/N] " ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "Aborted."; exit 1; }
fi

set -a; . ./.env; set +a
DB="${DATABASE_PATH:-instance/graduapp.sqlite}"

sudo systemctl stop "$SERVICE"

if [ -f "$DB" ]; then
  mkdir -p backups
  cp "$DB" "backups/graduapp-$(date +%Y%m%d-%H%M%S).sqlite"
fi
rm -f "$DB" "$DB-wal" "$DB-shm"

if [ "$PULL" -eq 1 ]; then
  git pull --ff-only
fi

if [ "$PIP" -eq 1 ]; then
  .linux_graduapp_venv/bin/pip install -q -e ".[prod]"
fi

.linux_graduapp_venv/bin/flask --app graduapp seed
sudo systemctl start "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" && echo "Game reset; $SERVICE is running." \
  || { echo "$SERVICE failed to start; see: journalctl -u $SERVICE -n 50" >&2; exit 1; }
