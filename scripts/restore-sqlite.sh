#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# COMPOSE_FILE must contain the same files used for deployment, including backup overlay.
snapshot="${1:-}"
mode="${2:-test}"
if [[ -z "$snapshot" || ( "$mode" != test && "$mode" != --main ) ]]; then
  echo 'Usage: scripts/restore-sqlite.sh <snapshot-id|latest> [test|--main]' >&2
  exit 1
fi
candidate="/backups/restore-$(date -u +%Y%m%dT%H%M%S)-$$.db"
docker compose run --rm --no-deps backup python -m app.backup restore \
  --snapshot "$snapshot" --output "$candidate"
echo "Verified candidate: $candidate (backup-data volume)"
if [[ "$mode" == test ]]; then
  exit 0
fi
# --main explicitly requests a maintenance window and replacement of the live database.
docker compose stop worker publisher backup
if [[ -n "$(docker compose ps --status running -q worker publisher backup migrate)" ]]; then
  echo 'Database services are still running; refusing replacement.' >&2
  exit 1
fi
docker compose run --rm --no-deps backup python -m app.backup activate \
  --offline --output "$candidate"
docker compose run --rm --no-deps migrate
docker compose up -d worker publisher backup
echo 'Database restored; services started. Check logs and dashboard freshness.'
