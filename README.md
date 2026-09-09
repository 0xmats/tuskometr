# Tuskometr

A live dashboard counting mentions of “Tusk” in a Polish TV stream.

- **Local:** Docker runs SQLite, transcription, publishing and a static web server.
- **Production:** the VPS processes audio and uploads JSON to R2; Cloudflare Pages hosts the frontend.
- SQLite keeps transcripts for 30 days and detected mentions indefinitely. Audio is not stored.

The dashboard lists mentions by broadcast time, newest first, including backfilled
results. Clicking a time band on the chart shows all
mentions in that interval; “Wróć do live” restores the current list. The last-hour
chart uses minute buckets. The 7-day range appears after more than 24 hours of
history; the 30-day range appears after more than 7 days. Publishers include static per-bucket pages, so filtering does
not query the production database. Deploy both publisher and frontend for these
features; no database migration is needed.

The hourly record compares the current last-hour count with the largest count in
any consecutive 60 minutes across all stored mentions, including history older
than 30 days. Windows include both endpoints, matching the live counter; they end
at a mention timestamp, and the earliest ending window wins ties. A window can
begin before the first collected sample; missing coverage is not inferred. The
footer shows the earliest available data timestamp. All displayed dates use
Europe/Warsaw.

Clicking the record opens its mentions newest first, ten at a time, with a return
to live action. Publishers create separate record pages shared by all chart ranges;
R2 reuses unchanged record objects and keeps them active regardless of their age.
The browser fetches those pages only on selection. Record calculation streams
indexed timestamps from the full history in one pass and loads quotes only for
the winning hour and the normal 30-day chart range. Backfills and corrections to
an old record trigger publication too. No detection or database schema changes
are needed; deploy both publisher and frontend to enable the feature.

The publisher checks for changes every five seconds (`DASHBOARD_REFRESH_SECONDS=5`),
and the frontend checks the manifest every five seconds. New mentions, historical
inserts, edits, deletions and pipeline state/model/reconnect-count changes trigger
publication on the next check. Audio/transcript heartbeat timestamps and lag alone
do not trigger writes. During quiet periods, status and rolling charts refresh
every 60 seconds (`DASHBOARD_PUBLISH_INTERVAL_SECONDS=60`), capped at half the
stale-data threshold. A restart publishes immediately; failed publications retry
on the next check without advancing the schedule. Both local and R2 publishing
use this policy. Detection, transcription windows and the stored data are unchanged.

Publication, polling and network time are additional; the R2 manifest retains its
five-second cache TTL. In a quiet 30-day period, one publication per minute means
about 216,000 R2 writes for four dashboards and their manifest, versus about
2.59 million at one publication every five seconds. Changed history/bucket objects,
new mentions, state transitions, restarts and retries add operations; these figures
are estimates, not a guarantee of remaining within a free allowance. CDN caching
must be configured separately as described in [production setup](deploy/production.md).

Existing `.env` files with `DASHBOARD_REFRESH_SECONDS=30` override the new default:
set that value to `5` when releasing this change. Deploy backend and frontend
through **Build, Test and Deploy** from `main` for both improvements.

## Sharing results

“Udostępnij wynik” opens a preview of a compact 640 × 240 preview of a 1920 × 720 PNG generated in the browser,
using the displayed last-hour and today counts and publication time captured at
click time. The image matches the dashboard’s red and light statistic tiles, with the logo,
Republika channel label, two results, a short timestamp and the site address. The primary action copies the image directly when the clipboard API is available.
Supported browsers also offer native sharing of a single PNG, without a link preview.
Link copying is also available. Success briefly displays a checkmark on the action button.
Native sharing passes only one PNG with no title, text or URL. Canceling does not copy anything;
failures allow retrying or copying the link.
The button is disabled until the last-hour result is available; zero is valid.
Demo images and messages are explicitly labeled.

The shared link always points to the live site's root, without query parameters,
fragments or embedded statistics. Opening it loads the normal live dashboard.
The image and message preserve the captured numbers and timestamp. Link previews
keep the static Tuskometr logo. Images are generated only after clicking, with no
server-side records or image storage. This feature adds no R2 storage, writes or
share-related reads; visits to the live site use its existing data publication
and caching policy.
No backend dependencies, deployment configuration or storage migrations are needed.

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

Historical gap filling is enabled by default (`YOUTUBE_HISTORY_ENABLED=true`).
After processing current audio, the worker scans the available DVR window for
missing transcript intervals, including time before its first successful start.
It processes one historical window (up to 300 seconds) before returning to current
audio. Live catch-up takes priority when behind by more than one live window.
Coverage uses transcript ranges, including silence and segments with no mentions,
across all sessions of the configured source URL. Committed ranges are the durable
history progress: restarting the worker resumes the remaining gaps automatically.
No new schema or reset of the live checkpoint is needed.

Historical detections are accepted only in still-uncovered intervals, with
additional same-source deduplication across sessions. Historical results publish
with their original source timestamps; they do not overwrite live status or send
collecting heartbeats. Logs prefixed `Historia DVR:` report the selected gap,
committed window, completion, or a retryable failure. Set
`YOUTUBE_HISTORY_ENABLED=false` to disable historical scanning independently of
normal DVR resume. Old session timestamps may be approximate; the current encoder
and its available DVR window bound what can be recovered. There is no archive
beyond that window, and the scanner does not claim unavailable audio is recovered.

The live checkpoint still starts with the next source fragment on first activation.
If a saved live position has left the DVR window, the worker records an interval
in `ingestion_gaps`, logs a warning and continues from the oldest allowed fragment
(with two fragments of margin). A changed encoder generation starts a new source
session and resumes by time where available. HTTP/decoding errors inside the
window are retried, not skipped.

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

For frontend work, only Node.js 22+ is needed:

```bash
npm ci
npm run dev
```

Open `http://127.0.0.1:3003`. Changes to the frontend reload automatically. Stop
with Ctrl+C. This starts only Vite and uses the editable synthetic fixture
[`apps/web/dev/dashboard.json`](apps/web/dev/dashboard.json). Saving that JSON
reloads the preview. No connection to production or YouTube is made, and no
local ingestion, transcription, publisher or database starts.

The fixture contains relative `minutesAgo` timestamps, sample quotes and pipeline
status. Dates are anchored to the moment the fixture loads. Charts, summary
counts, form counts, pagination and bucket filtering are derived from the same
rows for all four ranges. Adjust `historyDays` to test range availability and
`status.state` to test offline states. `staleAfterSeconds` is deliberately large
for a stable design preview; lower it to test the stale-data notice. Source-video
links are unavailable in mock mode because no YouTube player is loaded.

To opt into real published JSON, set `TUSKOMETR_DATA_ORIGIN` in the root `.env`
(or the shell), for example `https://data.tuskometr.com`, then restart the preview.
Vite proxies those requests without changing production CORS. Leave the setting
empty for the default offline fixtures. Mock data is served only in development
and is not included in the production build.

On the home Linux device, run the preview in the background:

```bash
npm run dev:start
npm run dev:stop
npm run dev:status
```

The bundled systemd user service exposes it at `http://100.80.64.94:3003`.
It does not start automatically at boot. The unit contains this device's paths;
use `npm run dev` on other machines. Stop the background preview before running
`npm run dev` in a terminal, since both use port 3003.

To explicitly run the full local processing stack (requires Docker Compose):

```bash
npm run dev:full
```

This starts local ingestion, transcription, publishing and the frontend, using
local JSON on port 8000. Ctrl+C stops that stack. Local transcription needs a
reasonably fast CPU and about 8 GB RAM; alternatively set `ASR_PROVIDER=ovh` and
`ASR_API_KEY` in `.env`. `npm start` also starts the full built Docker stack;
`npm stop` stops it. Avoid `docker compose down -v`, which deletes local data.

The production home proxy uses the separate `tuskometr-egress` Compose project.
All of these development start/stop commands leave that proxy running.

## Production

Complete the one-time [Cloudflare and VPS setup](deploy/production.md), configure
the GitHub `production` environment, then run **Build, Test and Deploy** from
`main`. Production deployments use GitHub Actions exclusively: CI builds and
pushes the image to GHCR; the VPS receives deployment files and pulls the image.
Do not copy application sources or build images on the VPS.

There are only two Compose files. Each is standalone; do not combine them.
Local and production use separate project names, images and volumes.
`npm run build:web` builds only the frontend; `npm run build:api` builds the Docker runtime.
Production opens no incoming ports and includes remote backups.
YouTube uses yt-dlp, Deno and FFmpeg with anonymous access. Production routes
YouTube metadata and audio through a [home connection over Tailscale](deploy/youtube-egress.md),
while processing and publishing stay on the VPS. No exported account cookies
or separate PO token generator are used.
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

Server-side fragment-link calibration, fallback and release checks are described
in [deploy/youtube-timeline.md](deploy/youtube-timeline.md).
