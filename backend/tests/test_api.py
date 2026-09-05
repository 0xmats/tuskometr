from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import router
from app.db import get_db
from app.models import Base, Occurrence, PipelineState, SourceSession


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with factory() as db:
        source = SourceSession(
            source_type="youtube",
            source_url="https://www.youtube.com/watch?v=test",
            started_at=now - timedelta(hours=1),
            status="live",
        )
        db.add(source)
        db.flush()
        db.add_all(
            [
                Occurrence(
                    source_session_id=source.id,
                    occurred_at=now - timedelta(minutes=20),
                    source_sample=100,
                    form="Tusk",
                    normalized_form="tusk",
                    quote="Donald Tusk zabrał głos",
                    confidence=0.94,
                    source_position_seconds=12.5,
                ),
                Occurrence(
                    source_session_id=source.id,
                    occurred_at=now - timedelta(minutes=10),
                    source_sample=200,
                    form="Tuska",
                    normalized_form="tuska",
                    quote="wypowiedź Donalda Tuska",
                    confidence=0.9,
                    source_position_seconds=22.5,
                ),
            ]
        )
        db.add(
            PipelineState(
                id=1,
                state="live",
                reconnect_count=2,
                lag_seconds=31,
                model_name="small",
                updated_at=now,
            )
        )
        db.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client


def test_occurrences_are_newest_first_and_camel_case(client: TestClient) -> None:
    response = client.get("/api/occurrences?limit=1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["form"] == "Tuska"
    assert payload["items"][0]["sourceUrl"].endswith("test")
    assert payload["items"][0]["sourcePositionSeconds"] == 22.5
    assert payload["nextCursor"] is not None


def test_stats_and_form_breakdown(client: TestClient) -> None:
    start = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    response = client.get("/api/stats", params={"from": start, "bucket": "hour"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["range"]["total"] == 2
    assert payload["summary"]["last24Hours"] == 2
    assert {item["form"] for item in payload["forms"]} == {"Tusk", "Tuska"}


def test_status_exposes_pipeline_health(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["state"] == "live"
    assert response.json()["lagSeconds"] == 31


def test_rejects_invalid_stats_range(client: TestClient) -> None:
    now = datetime.now(UTC)
    response = client.get(
        "/api/stats",
        params={"from": now.isoformat(), "to": (now - timedelta(hours=1)).isoformat()},
    )
    assert response.status_code == 422
