from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.models import Event, HistoricalDelay, LivePosition, Route, RouteStop, Station
from app.seed import seed_network
from simulator.engine import Fleet


@pytest.fixture
def position(dataset):
    fleet = Fleet(dataset, datetime(2026, 1, 1, tzinfo=UTC), seed=42)
    fleet.advance(5)
    return fleet.trains[0].snapshot()


def test_seed_is_idempotent_and_postgis_geometries_are_valid(db):
    counts = [
        db.scalar(select(func.count()).select_from(model)) for model in (Station, Route, RouteStop)
    ]
    seed_network(db)
    assert [
        db.scalar(select(func.count()).select_from(model)) for model in (Station, Route, RouteStop)
    ] == counts
    assert counts[0:2] == [63, 6]
    assert db.scalar(select(func.count()).select_from(HistoricalDelay)) == 0
    assert db.scalar(
        text(
            "SELECT bool_and(ST_IsValid(geom) AND ST_SRID(geom)=4326 "
            "AND ST_Length(geom::geography)>0) FROM routes"
        )
    )
    assert db.scalar(text("SELECT bool_and(ST_X(geom)=lon AND ST_Y(geom)=lat) FROM stations"))


def test_position_is_stored_and_retry_is_idempotent(db, request_api, position):
    assert request_api("POST", "/ingest/position", position).status_code == 201
    retry = request_api("POST", "/ingest/position", position)
    assert retry.status_code == 200 and retry.json()["status"] == "duplicate"
    assert db.scalar(select(func.count()).select_from(LivePosition)) == 1
    record = db.scalar(select(LivePosition))
    assert record.timestamp.tzinfo is not None
    assert record.source == "simulator"
    assert db.scalar(text("SELECT ST_X(geom)=lon AND ST_Y(geom)=lat FROM live_positions"))
    changed = {**position, "delay_minutes": 10}
    assert request_api("POST", "/ingest/position", changed).status_code == 409


def test_positions_cannot_move_backwards_or_replace_timestamp(db, request_api, position):
    assert request_api("POST", "/ingest/position", position).status_code == 201
    assert (
        request_api("POST", "/ingest/position", {**position, "id": str(uuid4())}).status_code == 409
    )
    older = {**position, "id": str(uuid4()), "timestamp": "2026-01-01T00:00:04Z"}
    assert request_api("POST", "/ingest/position", older).status_code == 409


@pytest.mark.parametrize(
    "update, status",
    [
        ({"train_number": "99999"}, 404),
        ({"last_station": "NDLS"}, 422),
        ({"next_station": "SBC"}, 422),
        ({"distance_km": 9999}, 422),
        ({"lat": 0, "lon": 0}, 422),
        ({"current_speed_kmh": -1}, 422),
        ({"delay_minutes": -1}, 422),
        ({"timestamp": "2026-01-01T00:00:00"}, 422),
        ({"source": "live"}, 422),
        ({"unexpected": "field"}, 422),
    ],
)
def test_rejects_invalid_telemetry(db, request_api, position, update, status):
    response = request_api("POST", "/ingest/position", {**position, **update})
    assert response.status_code == status, response.text
    assert db.scalar(select(func.count()).select_from(LivePosition)) == 0


def test_event_retry_and_validation(db, request_api, position):
    payload = {key: position[key] for key in ("id", "journey_id", "train_number", "timestamp")}
    payload.update(
        event_type="unscheduled_stop",
        severity=2,
        duration_seconds=120,
        description="Synthetic unscheduled stop",
    )
    assert request_api("POST", "/ingest/event", payload).status_code == 201
    assert request_api("POST", "/ingest/event", payload).status_code == 200
    assert db.scalar(select(func.count()).select_from(Event)) == 1
    assert request_api("POST", "/ingest/event", {**payload, "severity": 3}).status_code == 409
    assert (
        request_api("POST", "/ingest/event", {**payload, "event_type": "derailment"}).status_code
        == 422
    )
    assert (
        request_api("POST", "/ingest/event", {**payload, "duration_seconds": 0}).status_code == 422
    )


def test_terminal_station_accepts_zero_speed_only(db, request_api, dataset):
    fleet = Fleet(dataset, datetime.now(UTC), seed=42)
    train = fleet.trains[0]
    train.clock = (
        train.route["stops"][-1]["arrival_seconds"] - train.route["stops"][0]["departure_seconds"]
    )
    train.elapsed = train.clock
    payload = train.snapshot()
    assert payload["next_station"] is None
    assert (
        request_api("POST", "/ingest/position", {**payload, "current_speed_kmh": 1}).status_code
        == 422
    )
    assert request_api("POST", "/ingest/position", payload).status_code == 201


def test_offset_timestamps_are_normalized_to_utc(db, request_api, position):
    instant = datetime.fromisoformat(position["timestamp"])
    from datetime import timezone

    position["timestamp"] = instant.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()
    assert request_api("POST", "/ingest/position", position).status_code == 201
    assert db.scalar(select(LivePosition)).timestamp == instant


def test_backwards_distance_and_impossible_jump_are_rejected(db, request_api, dataset, position):
    assert request_api("POST", "/ingest/position", position).status_code == 201
    fleet = Fleet(dataset, datetime(2026, 1, 1, tzinfo=UTC), seed=42)
    backward = fleet.trains[0].snapshot()
    backward.update(journey_id=position["journey_id"], timestamp="2026-01-01T00:00:10Z")
    assert request_api("POST", "/ingest/position", backward).status_code == 409
    fleet.trains[0].clock = 600
    jumped = fleet.trains[0].snapshot()
    jumped.update(journey_id=position["journey_id"], timestamp="2026-01-01T00:00:06Z")
    assert request_api("POST", "/ingest/position", jumped).status_code == 422


def test_database_failure_is_sanitized(request_api, position):
    from sqlalchemy.exc import OperationalError

    from app.database import get_session
    from app.main import app

    def unavailable():
        raise OperationalError("private SQL", {}, Exception("secret-password"))

    app.dependency_overrides[get_session] = unavailable
    try:
        response = request_api("POST", "/ingest/position", position)
        assert response.status_code == 503
        assert response.json() == {"detail": "Telemetry store unavailable"}
        assert "secret-password" not in response.text
    finally:
        app.dependency_overrides.pop(get_session, None)
