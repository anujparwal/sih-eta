"""Keep documented endpoints, registered routes and database-backed smoke cases aligned."""

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from starlette.routing import WebSocketRoute

from app import read_api
from app.main import app
from app.read_schemas import (
    FleetStatus,
    JourneyHistory,
    Network,
    StationArrivals,
    TrainETA,
    TrainList,
)
from app.schemas import IngestResult
from simulator.engine import Fleet

CASES = [
    ("GET", "/health", None),
    ("GET", "/ready", None),
    ("POST", "/ingest/position", IngestResult),
    ("POST", "/ingest/event", IngestResult),
    ("GET", "/network", Network),
    ("GET", "/trains", TrainList),
    ("GET", "/trains/{train_number}/eta", TrainETA),
    ("GET", "/trains/{train_number}/history", JourneyHistory),
    ("GET", "/stations/{code}/arrivals", StationArrivals),
    ("GET", "/control/fleet-status", FleetStatus),
]
NOW = datetime(2026, 9, 17, 18, 40, tzinfo=UTC)


def test_every_documented_endpoint_has_a_registered_route_and_smoke_case():
    root = Path(__file__).resolve().parents[2]
    contract = root / "docs/api_contract.md"
    if not contract.exists():  # The backend image places tests and docs under /app.
        contract = Path(__file__).resolve().parents[1] / "docs/api_contract.md"
    documented = set(re.findall(r"^\| (GET|POST|WS) \| `([^`]+)`", contract.read_text(), re.M))
    http = {
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }
    sockets = {
        ("WS", route.path) for route in read_api.router.routes if isinstance(route, WebSocketRoute)
    }
    assert documented == http | sockets
    assert http == {(method, path) for method, path, _ in CASES}
    # The push-path contract is exercised by test_realtime_workers.py using two processes.
    assert sockets == {("WS", "/ws/trains/{train_number}")}


@pytest.mark.parametrize("method,template,model", CASES, ids=[f"{m} {p}" for m, p, _ in CASES])
def test_endpoint_contract_against_real_stores(
    db, db_engine, redis_client, request_api, dataset, monkeypatch, method, template, model
):
    database = make_url(os.environ["TEST_DATABASE_URL"])
    for key, value in {
        "POSTGRES_HOST": database.host,
        "POSTGRES_PORT": str(database.port or 5432),
        "POSTGRES_DB": database.database,
        "POSTGRES_USER": database.username,
        "POSTGRES_PASSWORD": database.password,
        "REDIS_URL": os.environ["TEST_REDIS_URL"],
    }.items():
        if value is not None:
            monkeypatch.setenv(key, value)
    app.dependency_overrides[read_api.utc_now] = lambda: NOW
    try:
        train = Fleet(dataset, NOW - timedelta(minutes=10), seed=42).trains[0]
        train.elapsed, train.clock = 600, 300
        position = train.snapshot()
        event = {
            "id": str(uuid4()),
            "journey_id": position["journey_id"],
            "train_number": "12301",
            "timestamp": NOW.isoformat(),
            "event_type": "weather",
            "severity": 2,
            "duration_seconds": 120,
            "description": "Synthetic contract-test incident",
        }
        if method == "GET":
            assert request_api("POST", "/ingest/position", position).status_code == 201
            assert request_api("POST", "/ingest/event", event).status_code == 201
        path = template.format(train_number="12301", code="DKAE")
        body = (position if path.endswith("position") else event) if method == "POST" else None
        response = request_api(method, path, body)
        assert response.status_code == (201 if method == "POST" else 200), response.text
        data = response.json()
        if model:
            model.model_validate(data)
        if path == "/ready":
            assert data == {"status": "ok", "dependencies": {"postgres": "ok", "redis": "ok"}}
        elif path == "/health":
            assert data == {"status": "ok"}
        elif path.endswith("/eta"):
            assert data["position_id"] == position["id"]
            assert data["active_events"][0]["id"] == event["id"]
            assert data["features"]["active_event_count"] == 1
        elif path.endswith("/history"):
            assert [p["id"] for p in data["positions"]] == [position["id"]]
        elif path.endswith("/arrivals"):
            assert [row["train_number"] for row in data["arrivals"]] == ["12301"]
        elif path in {"/trains", "/control/fleet-status"}:
            assert len(data["trains"]) == 6
            assert data["trains"][0]["latest_position"]["id"] == position["id"]
        elif method == "POST":
            assert data == {"id": body["id"], "status": "created"}
    finally:
        app.dependency_overrides.pop(read_api.utc_now, None)


@pytest.mark.parametrize(
    "path",
    [
        "/trains?active_only=perhaps",
        "/stations/NDLS/arrivals?include_stale=perhaps",
        "/trains/12301/history?journey_id=not-a-uuid",
        "/trains/12301/history?after=not-a-date",
        "/trains/12301/history?limit=1.5",
        "/trains/abc/history",
    ],
)
def test_malformed_read_queries_return_structured_validation_errors(db, request_api, path):
    response = request_api("GET", path, None)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
