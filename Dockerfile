FROM node:22-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FRONTEND_DIST=/app/static \
    HF_HOME=/models/huggingface

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=frontend-builder /build/frontend/dist /app/static

RUN mkdir -p /data /models /backups && chown -R 10001:10001 /app /data /models /backups
USER 10001:10001

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
