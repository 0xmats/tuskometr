# Tuskometr

A live dashboard counting mentions of “Tusk” in a Polish TV stream.

- **Local:** Docker runs SQLite, transcription, publishing and a static web server.
- **Production:** the VPS processes audio and uploads JSON to R2; Cloudflare Pages hosts the frontend.
- SQLite keeps transcripts for 30 days and detected mentions indefinitely. Audio is not stored.

## Run locally

Requires Docker Compose and Node.js 22+. Local transcription needs a reasonably
fast CPU and about 8 GB RAM; use OVH API to reduce local resource requirements.

```bash
cp .env.example .env
npm --prefix frontend ci
./scripts/dev-server.sh
```

Open `http://127.0.0.1:3003`. The frontend reloads automatically; restart the relevant
container after backend edits. Set `ASR_PROVIDER=ovh` and `ASR_API_KEY` in `.env`
to use OVH instead of local transcription. Leave `VITE_DATA_ORIGIN` unset locally.

To run the built dashboard without the development server:

```bash
docker compose up -d --build
```

Open `http://127.0.0.1:8000`. Stop with `docker compose down`; never add `-v`
unless you intend to delete the stored data.

## Production

Complete the one-time [Cloudflare and VPS setup](deploy/production.md), then:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

To release through GitHub Actions, configure the `production` environment as
described in the setup guide, then run **Release production** from `main`.

There are only two Compose files. Each is standalone; do not combine them.
Local and production use separate project names, images and volumes.
Production opens no incoming ports and includes remote backups.
See [backup and restore commands](deploy/backups.md).

## Checks

```bash
python3 -m venv .venv
.venv/bin/pip install -e './backend[dev]'
.venv/bin/pytest backend/tests
npm --prefix frontend run test:data
npm --prefix frontend run build
```

The restic integration test requires the `restic` executable.
Use a source you are authorized to process; public YouTube availability alone
is not permission for automated extraction.
