FROM node:22-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM restic/restic:0.18.1 AS restic

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/huggingface

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg curl tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=restic /usr/bin/restic /usr/local/bin/restic

WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

RUN mkdir -p /data /models /backups /snapshots && chown -R 10001:10001 /app /data /models /backups /snapshots
USER 10001:10001

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.publisher"]

FROM caddy:2.10-alpine AS web
COPY --from=frontend-builder /build/frontend/dist /srv
COPY deploy/Caddyfile.web /etc/caddy/Caddyfile
RUN mkdir -p /snapshots && chown 10001:10001 /snapshots
EXPOSE 8080
