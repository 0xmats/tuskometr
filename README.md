# Tuskometr

A live dashboard counting mentions of “Tusk” in a Polish TV stream.

- **Local:** Docker runs SQLite, transcription, publishing and a static web server.
- **Production:** the VPS processes audio and uploads JSON to R2; Cloudflare Pages hosts the frontend.
- SQLite keeps transcripts for 30 days and detected mentions indefinitely. Audio is not stored.

## Recovery after interruptions

YouTube ingestion uses its DVR window by default (`YOUTUBE_DVR_ENABLED=true`,
`YOUTUBE_DVR_HOURS=12`). SQLite stores the stream generation, source sequence and
next audio sample. Transcripts, mentions and progress commit in one transaction.
After a worker restart or a source/ASR error, the worker downloads the outstanding
fragments oldest first, without real-time throttling. Audio stays in a bounded
in-memory window; it is not archived on disk. Overlapping windows and replayed
windows deduplicate mentions within the same source timeline.

Backlogs of at least five minutes use 300-second transcription windows, advancing
295 seconds with the default five-second overlap. Near the live head, the worker
switches back to `CHUNK_SECONDS=25` / `CHUNK_STEP_SECONDS=20`; it does not wait for
five minutes of fresh audio. Set `YOUTUBE_DVR_CATCHUP_CHUNK_SECONDS=120` for smaller
catch-up requests, or set it equal to `CHUNK_SECONDS` to disable larger batches.
The overlap follows the live window settings. Each window commits independently,
so catch-up results appear in larger batches. A failed request retries from its
unchanged checkpoint. Existing short segments can coexist with longer segments;
no database migration is required. Five minutes of 16 kHz PCM uses about 9.6 MB
per audio buffer (temporary copies and ASR memory are additional).

The first activation starts with the next live fragment: earlier gaps cannot be
reconstructed from the legacy worker's session-relative offsets. Subsequent
interruptions recover automatically. If the saved position has left the DVR
window, the worker records an interval in `ingestion_gaps`, logs a warning and
continues from the oldest allowed fragment (with two fragments of margin).
A changed encoder generation starts a new source session and resumes by time
where available. HTTP/decoding errors inside the window are retried, not skipped.

The `DVR: wznawianie…` log reports the saved and current source sequences;
`lag` reports how far processing is behind the source clock. Media positions are
preserved across restarts. Their UTC anchor is estimated once from YouTube's head
headers, with accuracy of approximately one source fragment (about 5 seconds).
Keep `SAMPLE_RATE` unchanged while resuming the same stream generation.

Migration `0004` adds the progress and gap tables; the normal deployment runs it.
Set `YOUTUBE_DVR_ENABLED=false` to use the previous live-only reader. File and
direct URL sources retain their existing behavior. DVR extraction uses yt-dlp's
default clients and AAC format 140; it does not force the live-only `mweb` client.

## Structure

- `apps/web`: React/Vite frontend (npm workspace).
- `apps/api`: Python processing, SQLite, publishing and backups.
- Root `package.json`: shared development, build, test and production commands.

## Run locally

Requires Docker Compose and Node.js 22+. Local transcription needs a reasonably
fast CPU and about 8 GB RAM; use OVH API to reduce local resource requirements.

```bash
cp .env.example .env
npm ci
npm run dev
```

Open `http://127.0.0.1:3003`. The frontend reloads automatically; restart the relevant
container after backend edits. Set `ASR_PROVIDER=ovh` and `ASR_API_KEY` in `.env`
to use OVH instead of local transcription. Leave `VITE_DATA_ORIGIN` unset locally.

To run the built dashboard without the development server:

```bash
npm start
```

Open `http://127.0.0.1:8000`. Stop with `docker compose down`; never add `-v`
unless you intend to delete the stored data.

## Production

Complete the one-time [Cloudflare and VPS setup](deploy/production.md), then:

```bash
npm run prod:up
```

To release through GitHub Actions, configure the `production` environment as
described in the setup guide, then run **Build, Test and Deploy** from `main`.

There are only two Compose files. Each is standalone; do not combine them.
Local and production use separate project names, images and volumes.
`npm run build:web` builds only the frontend; `npm run build:api` builds the Docker runtime.
Production opens no incoming ports and includes remote backups.
YouTube uses Deno and an automatic PO token provider, started by Compose.
No manual token setup is required; YouTube can still restrict server IPs.
See [backup and restore commands](deploy/backups.md).

## Checks

```bash
python3 -m venv .venv
npm run api:install
npm test
npm run build
```

The restic integration test requires the `restic` executable.
Use a source you are authorized to process; public YouTube availability alone
is not permission for automated extraction.
