#!/usr/bin/env bash
set -Eeuo pipefail
release_dir="$(cd "$(dirname "$0")/.." && pwd)"
root=/opt/tuskometr
image="${1:?Pass the GHCR image digest}"
registry_user="${2:?Pass the GHCR user}"
initialize_backups="${3:-false}"
[[ "$initialize_backups" == true || "$initialize_backups" == false ]]
[[ "$release_dir" =~ ^/opt/tuskometr/releases/[a-f0-9]{40}$ ]]
[[ "$image" =~ ^ghcr.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]
[[ "$registry_user" =~ ^[A-Za-z0-9_-]+(\[bot\])?$ ]]
cd "$release_dir"
exec 9>"$root/.deploy.lock"
flock -n 9
# Runtime credentials are provisioned once on the server, not uploaded by Actions.
test -f "$root/.env"
test -f "$root/deploy/backup.env"
ln -sfn "$root/.env" .env
ln -sfn "$root/deploy/backup.env" deploy/backup.env
export TUSKOMETR_IMAGE="$image"
export DOCKER_CONFIG
DOCKER_CONFIG="$(mktemp -d)"
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
docker login ghcr.io --username "$registry_user" --password-stdin
compose=(docker compose -f docker-compose.prod.yml)
"${compose[@]}" config --quiet
"${compose[@]}" pull
if [[ "$initialize_backups" == true ]]; then
  "${compose[@]}" run --rm --no-deps backup python -m app.backup init
fi
# Check the existing private backup repository before changing running services.
"${compose[@]}" run --rm --no-deps backup python -m app.backup list
"${compose[@]}" up -d --no-build --wait --wait-timeout 90 youtube-tokens
"${compose[@]}" stop worker publisher backup
# Back up an existing database before running migrations. Fresh volumes have no DB.
"${compose[@]}" run --rm --no-deps backup python -c '
from pathlib import Path
from app.backup import backup_once
p = Path("/data/tuskometr.db")
if p.exists():
    backup_once(p, Path("/backups"), 7)
'
# Keep the canonical migration service on the release image. A one-off `run`
# leaves an old migrate container behind, which later `compose start` can reuse.
"${compose[@]}" up --no-build --no-deps --force-recreate --exit-code-from migrate migrate
"${compose[@]}" up -d --no-build --no-deps worker publisher backup
# Verify a new R2 manifest from this publisher, without relying on CDN caches.
"${compose[@]}" exec -T publisher python - <<'PY'
import json
import time
from datetime import datetime, timezone
from app.config import get_settings
import boto3
from botocore.config import Config
s = get_settings()
client = boto3.client('s3', endpoint_url=s.r2_endpoint_url, region_name='auto',
    aws_access_key_id=s.r2_access_key_id,
    aws_secret_access_key=s.r2_secret_access_key.get_secret_value(),
    config=Config(connect_timeout=5, read_timeout=5, retries={'max_attempts': 1}))
started = time.time()
for attempt in range(24):
    try:
        response = client.get_object(Bucket=s.r2_bucket, Key='dashboard/manifest.json')
        manifest = json.loads(response['Body'].read())
        generated = datetime.fromisoformat(manifest['generatedAt']).astimezone(timezone.utc).timestamp()
        if generated >= started:
            print('New R2 publication verified')
            break
    except Exception:
        pass
    time.sleep(5)
else:
    raise SystemExit('Publisher did not produce a fresh manifest; inspect VPS logs')
PY
for service in youtube-tokens worker publisher backup; do
  test -n "$("${compose[@]}" ps --status running -q "$service")"
done
printf 'TUSKOMETR_IMAGE=%s\n' "$image" > .release.env
ln -sfn "$release_dir" "$root/current"
echo 'Backend deployed. No database rollback is performed automatically on failure.'
