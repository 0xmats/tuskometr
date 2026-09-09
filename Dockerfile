FROM node:22-alpine AS frontend-builder
WORKDIR /build
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci
COPY apps/web/ ./apps/web/
RUN npm run build:web

FROM restic/restic:0.18.1 AS restic
FROM denoland/deno:bin-2.9.6 AS deno

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/huggingface \
    DENO_DIR=/tmp/deno \
    DENO_NO_UPDATE_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg curl tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=restic /usr/bin/restic /usr/local/bin/restic
COPY --from=deno /deno /usr/local/bin/deno

WORKDIR /app/apps/api
COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
RUN pip install --no-cache-dir . \
    && python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic

RUN mkdir -p /data /models /backups /snapshots /timeline && chown -R 10001:10001 /app /data /models /backups /snapshots /timeline
USER 10001:10001

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.publisher"]

FROM caddy:2.10-alpine AS web
COPY --from=frontend-builder /build/apps/web/dist /srv
COPY deploy/Caddyfile.web /etc/caddy/Caddyfile
RUN mkdir -p /snapshots && chown 10001:10001 /snapshots
EXPOSE 8080
