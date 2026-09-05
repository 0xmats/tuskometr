from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import get_settings
from .db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Tuskometr API",
    version="0.1.0",
    description="Read-only API for automatically detected Tusk surname occurrences.",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/healthz", include_in_schema=False)
def healthcheck():
    return {"status": "ok"}


settings = get_settings()
frontend_dist = settings.frontend_dist
if frontend_dist.exists():
    assets = frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str):
        candidate = frontend_dist / full_path
        if full_path and candidate.is_file() and frontend_dist in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
