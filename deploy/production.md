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
   Actions builds and uploads `frontend/dist`. If the project already uses Git
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
Release production → Run workflow → main**. It reruns tests, pushes an amd64 image
to GHCR, deploys the VPS by image digest, checks R2 publication, then uploads Pages.
A failed backend deployment prevents the Pages upload. These two deployments are
not atomic; if Pages fails, rerun the workflow. There is no automatic database rollback.

Create the GitHub environment `production` with these settings:

| Type | Name | Value |
| --- | --- | --- |
| Secret | `VPS_HOST` | SSH hostname/IP reachable from GitHub-hosted runners |
| Secret | `VPS_USER` | Deployment user with Docker access |
| Secret | `VPS_SSH_KEY` | Private deployment key |
| Secret | `VPS_KNOWN_HOSTS` | Verified SSH host-key entry, including port if nonstandard |
| Secret | `CLOUDFLARE_API_TOKEN` | Account token with Cloudflare Pages Edit |
| Variable | `VPS_PORT` | Optional SSH port, default `22` |
| Variable | `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |
| Variable | `CLOUDFLARE_PAGES_PROJECT` | Existing Pages project name |
| Variable | `VITE_DATA_ORIGIN` | Public R2 origin, e.g. `https://data.example.com` |

The VPS must be amd64 with Docker Compose, Bash and `flock`. Provision
`/opt/tuskometr`, owned by the deployment user. Store runtime settings in
`/opt/tuskometr/.env` and backup credentials in `/opt/tuskometr/deploy/backup.env`.
Initialize the backup repository once using the backup setup instructions before
starting the first release. Do not add runtime R2/OVH credentials to GitHub.
An address available only inside Tailscale is not reachable from this runner setup.
Verify the SSH host key through your existing trusted connection or VPS console.

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
