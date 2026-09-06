# YouTube through the home connection

The production worker, SQLite database, transcription and R2 publisher stay on
the VPS. Only YouTube metadata and audio use a home device's
connection, through an HTTP CONNECT proxy over Tailscale. Google account cookies
and external PO token plugins are disabled. yt-dlp, its bundled EJS scripts,
Deno and FFmpeg remain on the VPS.

This removes dependence on an exported login session, but cannot guarantee that
YouTube will never restrict the home connection. The device, Docker, Tailscale
and its internet connection must stay available. The existing collecting
heartbeat detects interrupted ingestion. DVR recovery remains limited to the
source's available window.

## Home device (Linux)

Both machines must be in the same Tailscale network, with access from the VPS to
the home device's TCP port 18888. Copy `deploy/youtube-egress/egress.env.example`
outside the checkout (for example `~/.config/tuskometr/egress.env`), and set the
two Tailscale IPv4 addresses. Then, from the repository root:

```bash
docker compose --env-file ~/.config/tuskometr/egress.env \
  -p tuskometr-egress -f docker-compose.yml \
  up -d --build --no-deps youtube-egress
```

The separate Compose project survives development-server shutdowns. The home
device needs only this proxy for production; the local development worker,
publisher and token provider can be stopped. Docker's
`unless-stopped` policy restarts it after a reboot; if Tailscale's address is not
ready, the container retries startup. Keep Docker and Tailscale enabled at boot.
The proxy binds only to the configured Tailscale address, allows that device and
the specified VPS, and limits destinations to YouTube/Google domains. It does not
listen on the LAN or public interface, and it does not terminate HTTPS.

```bash
docker logs --tail 50 tuskometr-egress-youtube-egress-1
```

## Production VPS

Deploy the backend version supporting `YOUTUBE_PROXY_URL`. In
`/opt/tuskometr/.env`, set (replace the address if needed):

```dotenv
YOUTUBE_PROXY_URL=http://100.80.64.94:18888
```

Recreate the worker using the deployed image and Compose file. Restarting the
same container does not reload its environment. Do not change the database or
run a second production worker against it.

The worker passes the proxy to yt-dlp and to `httpx` (DVR HEAD and fragment GET).
The live-only reader also passes it to FFmpeg.
R2, transcription and backups continue to use the VPS connection. An unreachable
proxy fails the read; there is no automatic fallback to the VPS IP.

## Verification

From the release directory, using its deployed image:

```bash
docker compose --env-file .env --env-file .release.env \
  -f docker-compose.prod.yml exec -T worker python -m app.youtube_check
```

This resolves a new DVR URL, reads its head, downloads a recent audio fragment
and decodes it. It never touches the database or submits audio for transcription.
The output reports success, sequence and byte count, without signed URLs or
cookies. For a 24-hour check that repeatedly resolves new URLs:

```bash
docker compose --env-file .env --env-file .release.env \
  -f docker-compose.prod.yml run -d --no-deps --name tuskometr-egress-check \
  worker python -m app.youtube_check --attempts 49 --interval 1800
docker logs --tail 60 tuskometr-egress-check
```

The check ends with a nonzero exit code if any probe failed. Remove its container
after reviewing the result. A single passing probe does not establish 24-hour
reliability; check live worker progress and the completed probe log as well.

To revert routing, clear `YOUTUBE_PROXY_URL` and recreate the worker. Stored
progress is retained, but anonymous access from the VPS must be verified first.
