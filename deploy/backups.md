# Backups and recovery

Local mode keeps seven SQLite snapshots on disk. Production also sends encrypted
snapshots through restic to a **separate private S3/R2 bucket**. Backups run at
startup and daily at 03:30 UTC; failures retry after five minutes. Remote retention
keeps the last 10 snapshots, 14 daily and 8 weekly snapshots.

## One-time setup

Create a private R2 Standard bucket with bucket-scoped S3 read/write credentials.
Do not enable public access or lifecycle deletion. Copy `backup.env.example` to
`/opt/tuskometr/deploy/backup.env`, fill in the credentials and a strong
`RESTIC_PASSWORD`, then:

```bash
chmod 600 /opt/tuskometr/deploy/backup.env
```

Run the GitHub Actions release with `initialize_backups` selected for this new
repository. Initialization uses the pulled image before services are stopped;
no source checkout or build is needed on the VPS. Leave the option disabled on
later releases. Initialization fails if the repository already exists.

Keep the password outside the VPS; losing it makes backups unrecoverable.
Keep `BACKUP_RESTIC_HOST` and the repository address stable across deployments.
Run `init` only for a new repository. The credentials are passed only to backup.

## Manual operations

```bash
# Create a backup now.
docker compose -f docker-compose.prod.yml run --rm --no-deps backup python -m app.backup once
# List recovery points.
docker compose -f docker-compose.prod.yml run --rm --no-deps backup python -m app.backup list
# Read and verify the complete repository.
docker compose -f docker-compose.prod.yml run --rm --no-deps backup python -m app.backup check
# Restore into a separate file and validate it without stopping the app.
./scripts/restore-sqlite.sh latest test
# Replace the main database during a maintenance window.
./scripts/restore-sqlite.sh SNAPSHOT_ID --main
```

Main restore downloads and validates first, stops database services, preserves
the previous database, replaces it, runs migrations and restarts services.
Do not run concurrent backup, restore or deployment commands, or other processes
accessing the database. If replacement/migration fails, services remain stopped.

Restored test files and raw copies of corrupt databases remain in `backup-data`
for inspection; delete them manually when no longer needed. Check backup logs:
external failure notifications are not configured.

## Lost VPS

Recover the code, `.env` and `backup.env`, build the images, then run the test and
main restore commands. **Do not initialize the existing repository again.**
The backup contains the main SQLite database, including retained transcripts.
It does not include credentials, models or the R2 publisher's upload registry.
The publisher regenerates JSON; losing its registry can leave old R2 objects
that need separate cleanup. Deleted transcripts may remain in retained backups.
