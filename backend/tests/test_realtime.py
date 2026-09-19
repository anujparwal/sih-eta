"""Real Redis scripts and API failure boundaries; no emulated cache implementation."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import func, select

from app import ingest, read_api, realtime
from app.database import get_session
from app.main import app
from app.models import LivePosition
from simulator.engine import Fleet

NOW = datetime(2026, 9, 17, 18, 40, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_cache_clock(monkeypatch):
    monkeypatch.setattr(realtime, "utc_now", lambda: NOW)


def payload(dataset, *, end=NOW, journey=None):
    fleet = Fleet(dataset, end - timedelta(seconds=5), seed=42)
    fleet.advance(5)
    result = fleet.trains[0].snapshot()
    if journey is not None:
        result["journey_id"] = journey
    return result


def test_commit_notification_cache_and_idempotent_retry(db, dataset, request_api, redis_client):
    sample = payload(dataset, end=datetime.now(UTC))
    with redis_client.pubsub() as subscription:
        subscription.subscribe(realtime.channel("12301"))
        assert subscription.get_message(timeout=1)["type"] == "subscribe"
        assert request_api("POST", "/ingest/position", sample).status_code == 201
        message = subscription.get_message(timeout=1)
        assert json.loads(message["data"])["id"] == sample["id"]
        assert db.get(LivePosition, UUID(sample["id"])) is not None
        row = realtime.cached_train(db, "12301", datetime.now(UTC))
        assert str(row.latest_position.id) == sample["id"]
        assert request_api("POST", "/ingest/position", sample).status_code == 200
        assert json.loads(subscription.get_message(timeout=1)["data"])["id"] == sample["id"]
        assert db.scalar(select(func.count()).select_from(LivePosition)) == 1
        changed = sample | {"delay_minutes": 99}
        assert request_api("POST", "/ingest/position", changed).status_code == 409
        assert subscription.get_message(timeout=0.05) is None


def test_post_commit_delivery_failure_can_be_repaired_with_same_uuid(
    db, dataset, request_api, redis_client, monkeypatch
):
    sample = payload(dataset)
    publish = ingest.publish_committed

    def unavailable(*_):
        raise ConnectionError("secret-realtime-password")

    monkeypatch.setattr(ingest, "publish_committed", unavailable)
    response = request_api("POST", "/ingest/position", sample)
    assert response.status_code == 503
    assert response.json() == {"detail": "Realtime store unavailable"}
    assert db.get(LivePosition, UUID(sample["id"])) is not None
    monkeypatch.setattr(ingest, "publish_committed", publish)
    assert request_api("POST", "/ingest/position", sample).status_code == 200
    assert db.scalar(select(func.count()).select_from(LivePosition)) == 1
    assert redis_client.get(realtime.state_keys("12301")[1]) is not None


def test_redis_failure_denies_ingest_before_database_write(db, dataset, request_api, monkeypatch):
    def unavailable(_):
        raise ConnectionError("secret-realtime-password")

    monkeypatch.setattr(realtime, "check_rate", unavailable)
    response = request_api("POST", "/ingest/position", payload(dataset))
    assert response.status_code == 503 and "secret" not in response.text
    assert db.scalar(select(func.count()).select_from(LivePosition)) == 0


def test_warm_fleet_cache_never_queries_database_and_status_still_ages(
    db, dataset, request_api, monkeypatch
):
    sample = payload(dataset)
    assert request_api("POST", "/ingest/position", sample).status_code == 201
    now = [NOW]
    app.dependency_overrides[read_api.utc_now] = lambda: now[0]
    try:
        assert request_api("GET", "/control/fleet-status", None).json()["active_trains"] == 1

        class NoDatabase:
            def __getattr__(self, name):
                raise AssertionError(f"Warm fleet read attempted DB access: {name}")

        app.dependency_overrides[get_session] = lambda: NoDatabase()
        now[0] += timedelta(seconds=30, microseconds=1)
        response = request_api("GET", "/control/fleet-status", None)
        assert response.status_code == 200, response.text
        assert response.json()["active_trains"] == 0
        assert response.json()["stale_trains"] == 1
        assert response.json()["mean_active_delay_minutes"] is None
    finally:
        app.dependency_overrides.pop(read_api.utc_now, None)
        app.dependency_overrides.pop(get_session, None)


def test_cache_future_boundary_eviction_and_old_retry_never_regress_latest(
    db, dataset, request_api, redis_client
):
    older = payload(dataset, end=NOW - timedelta(seconds=5))
    newer = payload(dataset, end=NOW + timedelta(seconds=5))
    for sample in [older, newer]:
        assert request_api("POST", "/ingest/position", sample).status_code == 201
    assert str(realtime.cached_train(db, "12301", NOW).latest_position.id) == older["id"]
    raw = realtime.CacheEntry.model_validate_json(redis_client.get(realtime.state_keys("12301")[1]))
    assert raw.valid_until == NOW + timedelta(seconds=5)
    assert (
        str(realtime.cached_train(db, "12301", NOW + timedelta(seconds=5)).latest_position.id)
        == newer["id"]
    )
    assert request_api("POST", "/ingest/position", older).status_code == 200
    assert (
        str(realtime.cached_train(db, "12301", NOW + timedelta(seconds=6)).latest_position.id)
        == newer["id"]
    )
    redis_client.delete(realtime.state_keys("12301")[1])
    assert (
        str(realtime.cached_train(db, "12301", NOW + timedelta(seconds=7)).latest_position.id)
        == newer["id"]
    )


def test_cache_fill_racing_commit_cannot_restore_invalidated_state(db, redis_client, monkeypatch):
    original = realtime.read_train_state

    def concurrent_write(session, number, now):
        entry = original(session, number, now)
        # Simulate another worker's commit notification while this reader was in SQL.
        redis_client.eval(
            realtime.NOTIFY_POSITION,
            3,
            *realtime.state_keys(number),
            realtime.channel(number),
            "{}",
        )
        return entry

    monkeypatch.setattr(realtime, "read_train_state", concurrent_write)
    realtime.cached_train(db, "12301", NOW)
    assert redis_client.get(realtime.state_keys("12301")[1]) is None
    monkeypatch.setattr(realtime, "read_train_state", original)
    realtime.cached_train(db, "12301", NOW)
    assert redis_client.get(realtime.state_keys("12301")[1]) is not None


def test_concurrent_rate_limit_is_atomic_and_expires(redis_client, monkeypatch):
    monkeypatch.setattr(realtime, "RATE_LIMIT", 10)
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(realtime.check_rate, ["same-peer"] * 40))
    assert sum(allowed for allowed, _ in results) == 10
    assert all(1 <= retry <= 60 for _, retry in results)
    key = next(redis_client.scan_iter(match=f"{realtime.KEY_PREFIX}:rate:*"))
    assert 0 < redis_client.pttl(key) <= 60000
    redis_client.pexpireat(key, 1)  # Expire this budget, using an already-past epoch.
    assert realtime.check_rate("same-peer")[0]
    assert realtime.check_rate("different-peer")[0]


def test_all_ingest_routes_share_budget_and_ignore_forwarded_headers(redis_client, monkeypatch):
    monkeypatch.setattr(realtime, "RATE_LIMIT", 2)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.post("/ingest/position", json={})).status_code == 422
            assert (await client.post("/ingest/event", json={})).status_code == 422
            denied = await client.post(
                "/ingest/position", json={}, headers={"X-Forwarded-For": "8.8.8.8"}
            )
            assert denied.status_code == 429
            assert 1 <= int(denied.headers["retry-after"]) <= 60
            assert (await client.get("/health")).status_code == 200

    asyncio.run(scenario())


def test_oversized_chunked_and_invalid_json_are_rejected_before_ingestion(redis_client):
    async def body():
        yield b"x" * 10000
        yield b"y" * 10000

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post("/ingest/position", content=body())
            assert response.status_code == 413
            assert (await client.post("/ingest/event", content=b"x" * 16385)).status_code == 413
            assert (await client.post("/ingest/event", content="{broken")).status_code == 422

    asyncio.run(scenario())


def test_event_notifications_use_the_same_train_channel(db, dataset, request_api, redis_client):
    sample = payload(dataset)
    event = {key: sample[key] for key in ["id", "journey_id", "train_number", "timestamp"]}
    event.update(
        event_type="weather", severity=1, duration_seconds=30, description="Synthetic rain"
    )
    with redis_client.pubsub() as subscription:
        subscription.subscribe(realtime.channel("12301"))
        subscription.get_message(timeout=1)
        assert request_api("POST", "/ingest/event", event).status_code == 201
        assert json.loads(subscription.get_message(timeout=1)["data"])["event_type"] == "weather"
        assert request_api("POST", "/ingest/event", event).status_code == 200
        assert json.loads(subscription.get_message(timeout=1)["data"])["id"] == event["id"]


def test_out_of_order_cache_fill_does_not_replace_newer_as_of(db, redis_client):
    realtime.cached_train(db, "12301", NOW + timedelta(seconds=1))
    realtime.fill_state(db, "12301", NOW, "0")
    raw = realtime.CacheEntry.model_validate_json(redis_client.get(realtime.state_keys("12301")[1]))
    assert raw.built_at == NOW + timedelta(seconds=1)


def test_nonfinite_json_numbers_cannot_crash_validation_response(redis_client):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            for token in ["NaN", "Infinity", "-Infinity", "1e9999"]:
                response = await client.post(
                    "/ingest/position",
                    content='{"lat":' + token + "}",
                    headers={"content-type": "application/json"},
                )
                assert response.status_code == 422
                assert response.json()["detail"] == "Body must be valid JSON with finite numbers"

    asyncio.run(scenario())


def test_corrupt_cache_is_replaced_without_using_invalid_timestamps(db, redis_client):
    key = realtime.state_keys("12301")[1]
    for bad in [
        "not-json",
        '{"built_at":"zzzz"}',
        '{"built_at":"2026-09-17T18:40:00","valid_until":"2026-09-17T18:41:00"}',
    ]:
        redis_client.set(key, bad, ex=60)
        state = realtime.cached_train(db, "12301", NOW)
        assert state.status == "no_data"
        repaired = realtime.CacheEntry.model_validate_json(redis_client.get(key))
        assert repaired.built_at == NOW


def test_real_pubsub_survives_idle_health_checks_and_coalesces_bursts(redis_client):
    async def scenario():
        async with realtime.subscribe("12301") as updates:
            # Longer than both the read timeout and Redis health-check interval.
            # An idle connection must stay subscribed and not emit phantom updates.
            await asyncio.sleep(6.1)
            assert updates.empty()
            assert redis_client.pubsub_numsub(realtime.channel("12301"))[0][1] == 1
            for _ in range(20):
                redis_client.publish(realtime.channel("12301"), "{}")
            await asyncio.sleep(0.05)
            assert updates.qsize() == 1
            assert await asyncio.wait_for(updates.get(), timeout=1) is True
        await asyncio.sleep(0.01)
        assert redis_client.pubsub_numsub(realtime.channel("12301"))[0][1] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"delay_minutes": 1e308},
        {"timestamp": "9999-12-31T23:59:59-01:00"},
        {"timestamp": "0001-01-01T00:00:00+01:00"},
        {"journey_started_at": "0001-01-01T00:00:00+01:00"},
    ],
)
def test_extreme_timeline_input_is_rejected_instead_of_breaking_eta(
    db, dataset, request_api, change
):
    response = request_api("POST", "/ingest/position", payload(dataset) | change)
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(LivePosition)) == 0
