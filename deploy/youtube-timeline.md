# Server-side YouTube timeline calibration

The `youtube-timeline` service runs a short, muted Chromium player session on the
VPS. It measures the live edge twice in independent browser contexts. Samples
must show advancing playback after seeking and agree within 10 seconds before
their average is published. Each attempt closes its browser; the next attempt
starts 60 seconds later. The service uses the same `YOUTUBE_PROXY_URL` as the audio
worker, with no fallback to direct access when a proxy is configured. It does not
read SQLite, transcribe audio, store Google cookies or modify the home Tinyproxy.

Only `videoId`, `origin`, `checkedAt` and `expiresAt` go into the public manifest's
`youtubeTimeline` field. The cache lives on a separate `timeline-data` volume,
mounted read-only in the publisher. Writes are atomic. The publisher validates
source identity and freshness and publishes changes on its next poll, including
expiry. A failed probe retains the last good result for at most 180 seconds;
disagreement between sessions immediately removes it. Container health checks
also fail when no valid result remains.

The frontend waits for its initial manifest and uses a fresh server result to
make all fragment links available with the dashboard data. Normal visits make no
YouTube player requests. Freshness uses the CDN's Date/Age headers and elapsed
monotonic time, rather than the device's wall clock. If the result is missing,
invalid or expired, the existing browser calibration loads dynamically as a
fallback. This also supports older publishers during rollout. Server recovery
cancels local calibration and its retries. Lighthouse may still report YouTube
warnings while this fallback is needed.

## Deployment

Use only **Build, Test and Deploy** on `main`. The existing GHCR runtime image now
includes Playwright 1.62.0 and its matching Chromium headless shell. Chromium only
runs in `youtube-timeline`, limited to one CPU and 768 MB RAM, with 256 MB shared
memory. This increases the runtime image size; the worker and publisher do not
launch browsers themselves.

The workflow's deployment script first performs a real calibration using a
separate temporary cache, before stopping existing services. It then starts the
periodic service and verifies a fresh calibration in the new R2 manifest before
deploying the frontend. A failed check stops deployment; it does not automatically
roll back an already migrated database.

`SOURCE_URL` must match in the worker, publisher and calibrator (Compose supplies
it to all three). `YOUTUBE_PLAYER_ORIGIN` defaults to `https://tuskometr.pages.dev`;
set it to the frontend HTTPS origin if that changes. The calibration document is
fulfilled inside the server browser, using that identity for the embed's origin
and Referer; no calibration page or inbound port is exposed publicly.

## Checks

Backend unit tests cover invalid/expired results, atomic cache replacement,
publication to local storage and R2, disagreement, player errors, stalled playback
and timeouts. The frontend unit tests cover freshness and clock skew. The built
frontend integration test additionally checks immediate links, zero YouTube
requests, manifest-only calibration updates, fallback and recovery:

```bash
npm run build:web
# Serve apps/web/dist using Vite preview, then in another terminal:
PLAYWRIGHT_MODULE_PATH=/path/to/node_modules/playwright \
  TEST_URL=http://127.0.0.1:4175 node apps/web/tests/server-timeline.cjs
```

A one-off measurement using an already deployed image can be run without touching
the live calibration cache:

```bash
docker compose --env-file .env --env-file .release.env \
  -f docker-compose.prod.yml run --rm --no-deps \
  -e YOUTUBE_TIMELINE_FILE=/tmp/youtube-check.json \
  youtube-timeline python -m app.youtube_timeline --once
```

Inspect service health/logs if calibration expires. A passing probe establishes
current access, not long-term reliability of YouTube or the proxy.
