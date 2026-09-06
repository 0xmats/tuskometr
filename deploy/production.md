# Production setup

## Cloudflare

1. Create an R2 Standard bucket for **public dashboard JSON** and attach a custom
   domain such as `data.example.com`. Do not use `r2.dev` for production.
2. Apply `r2-cors.json`, replacing the example frontend origins with your actual
   Pages/custom domains. Keep `Date` and `Age` exposed.
3. Add a Cache Rule for that domain and `/dashboard/*`: **Eligible for cache**,
   **Use cache-control header if present, bypass cache if not**, and **Respect
   origin** for browser TTL. Do not override TTLs or cache errors.
4. Create bucket-scoped S3 read/write credentials for the publisher.
5. Create a Pages Direct Upload project with production branch `main`.
   Actions builds and uploads `apps/web/dist`. If the project already uses Git
   integration, disable automatic deployments to avoid bypassing release checks.

## VPS

Copy `.env.example` to `.env`. Set the R2 endpoint, bucket and credentials.
For OVH transcription, set `ASR_PROVIDER=ovh` and `ASR_API_KEY`.
Configure the separate private backup repository using [backups.md](backups.md).
Then run:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f worker publisher backup
```

Use the same command after updates. Keep the project name `tuskometr` and its
volumes when moving an existing production installation. The local project is
`tuskometr-dev`; changing project names does not move existing data.
If migrating from the old configuration, stop its `web` and `caddy` containers;
the new production setup serves everything through Cloudflare.

Compose starts `youtube-tokens` automatically. The worker uses its internal
endpoint; no port or additional secret is needed. Releases check provider health
before restarting the worker. Inspect `worker` and `youtube-tokens` logs if YouTube
rejects a connection; token generation does not guarantee access from every IP.

If the VPS needs YouTube login cookies, keep the Netscape-format file in a
persistent worker volume, for example `/models/youtube-cookies.txt`, and set
`YTDLP_COOKIES_FILE=/models/youtube-cookies.txt` in `/opt/tuskometr/.env`.
The file must be readable and writable by UID 10001 (mode 600 is sufficient).
`/models` and `/data` survive normal releases; a file copied into `/tmp` or the
container's writable layer does not. The worker rejects a configured missing or
empty file. A file's existence alone does not establish that its login is valid.

For a metadata-only diagnostic using the worker's configured cookies and token
provider, run this from `/opt/tuskometr/current`:

```bash
docker compose -f docker-compose.prod.yml exec -T worker sh -c '
  yt-dlp --ignore-config --no-playlist --js-runtimes deno \
    --live-from-start --skip-download --print format_id --format 140 \
    --cookies "$YTDLP_COOKIES_FILE" \
    --extractor-args "youtubepot-bgutilhttp:base_url=$YTDLP_POT_PROVIDER_URL" \
    "$SOURCE_URL"
'
```

Use this command when `YTDLP_COOKIES_FILE` is configured. Running yt-dlp manually
without `--cookies` does not use that environment variable automatically.

The publisher uploads changed files, then switches the manifest. It removes
unreferenced objects after 24 hours. Do not add bucket lifecycle expiration or
manually delete active files. Keep one publisher per bucket and preserve its
`dashboard-data` volume; losing it causes reuploads and may leave orphaned objects.

## Verify

```bash
curl -sS -D - https://data.example.com/dashboard/manifest.json
```

Repeat within five seconds and check `CF-Cache-Status: HIT`. In the browser, check
updates, older mentions and CORS. Data should become stale after the publisher
has been stopped for over 120 seconds. After changing CORS, purge the data cache.

References: [Pages](https://developers.cloudflare.com/pages/framework-guides/deploy-a-vite3-project/),
[R2 CORS](https://developers.cloudflare.com/r2/buckets/cors/).

## GitHub Actions release

`Checks` runs on pushes to `main` and pull requests. To deploy, open **Actions →
Build, Test and Deploy → Run workflow → main**. It reruns tests, pushes an amd64 image
to GHCR, deploys the VPS by image digest, checks R2 publication, then uploads Pages.
A failed backend deployment prevents the Pages upload. These two deployments are
not atomic; if Pages fails, rerun the workflow. There is no automatic database rollback.

Create the GitHub environment `production` with these settings:

| Type | Name | Value |
| --- | --- | --- |
| Secret | `VPS_HOST` | SSH hostname/IP reachable from GitHub-hosted runners |
| Secret | `VPS_USER` | Deployment user with Docker access |
| Secret | `VPS_SSH_KEY` | Private deployment key |
| Secret | `CLOUDFLARE_API_TOKEN` | Account token with Cloudflare Pages Edit |
| Variable | `VPS_PORT` | Optional SSH port, default `22` |
| Variable | `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |
| Variable | `CLOUDFLARE_PAGES_PROJECT` | Existing Pages project name |
| Variable | `VITE_DATA_ORIGIN` | Public R2 origin, e.g. `https://data.example.com` |

The VPS must be amd64 with Docker Compose, Bash and `flock`. Provision
`/opt/tuskometr`, owned by the deployment user. Store runtime settings in
`/opt/tuskometr/.env` and backup credentials in `/opt/tuskometr/deploy/backup.env`.
For a new empty backup repository, select `initialize_backups` when running the
first release. Leave it disabled for subsequent releases or an existing repository.
Actions initializes backups using the pulled image; no checkout or build is needed
on the VPS. Do not add runtime R2/OVH credentials to GitHub.
An address available only inside Tailscale is not reachable from this runner setup.
The workflow populates SSH known hosts using `ssh-keyscan` during deployment.

Releases live in `/opt/tuskometr/releases/<commit>`; `current` points to the last
successful backend release. Shared Docker volumes remain under project `tuskometr`.
Before migrations, services stop and an existing database is backed up remotely.
Failures after stopping services may leave them stopped; inspect logs before retrying.
For manual operations after an Actions deployment:

```bash
cd /opt/tuskometr/current
export "$(cat .release.env)"
docker compose -f docker-compose.prod.yml logs --tail=100
```

For an application rollback, deploy a reviewed revert commit. Restore SQLite
separately if a schema migration requires it; changing the image alone does not
undo database changes.

## Alerts (optional)

Set `HEALTHCHECKS_COLLECTING_URL`, `HEALTHCHECKS_PUBLISHING_URL` and
`HEALTHCHECKS_BACKUP_URL` to their private Healthchecks ping URLs in
`/opt/tuskometr/.env`, then deploy through Actions. Leave empty to disable.
Use Simple checks: collecting/publishing period 1 minute, grace 4 minutes;
backup period 1 day, grace 2 hours. Enable your email integration for all three.

Signals follow successful audio processing and database writes, dashboard
publication, and remote backup respectively. Collecting/publishing send at most
once per minute. Failed checks recover on the next successful signal. Heartbeat
requests use a 3-second network timeout; failures do not stop application work.
These checks monitor processing and publication, not browser access or CORS.
Keep development ping URLs empty to avoid masking a production outage.
