"""Provider boundary, quota conservation, and real Redis cache isolation."""

import asyncio
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Event
from urllib.error import HTTPError, URLError

import httpx
import pytest
from fastapi import HTTPException, Response

from app import railradar, realtime
from app.main import app
from app.railradar import LiveResult, ProviderTrain


def payload(number="12953", journey_date=None):
    return {
        "success": True,
        "data": {
            "trainNumber": number,
            "trainName": "Test express",
            "startDate": str(journey_date or date.today()),
            "lastUpdatedAt": datetime.now(UTC).isoformat(),
            "isLive": True,
            "status": "running",
            "currentLocation": {"stationCode": "AAA", "stationName": "Test station"},
            "train": {"source": {"code": "AAA"}, "destination": {"code": "BBB"}},
            "route": [
                {
                    "sequence": 1,
                    "stationCode": "AAA",
                    "isHalt": True,
                    "actualArrival": "2026-09-23T00:10:00+05:30",
                }
            ],
        },
    }


def api(path):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(send())


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("RAILRADAR_API_KEY", "test-provider-key")
    monkeypatch.setenv("RAILRADAR_DAILY_LIMIT", "30")
    monkeypatch.setenv("RAILRADAR_MONTHLY_LIMIT", "900")
    calls = []

    def fetch(number, journey_date, key):
        calls.append((number, journey_date, key))
        return ProviderTrain.model_validate(payload(number, journey_date)["data"])

    monkeypatch.setattr(railradar, "fetch_provider", fetch)
    return calls


def test_missing_key_and_invalid_requests_never_call_provider(monkeypatch):
    monkeypatch.delenv("RAILRADAR_API_KEY", raising=False)
    assert api("/live/trains/12953").status_code == 503
    for path in ("/live/trains/1234", "/live/trains/abcde", "/live/trains/12953?date=2026-02-30"):
        assert api(path).status_code == 422


def test_normalization_preserves_unknowns_and_reported_times():
    data = ProviderTrain.model_validate(payload()["data"])
    assert data.delay_minutes is None
    assert data.current_location.is_actual_position is None
    assert data.train.source.station_code == "AAA"
    assert data.route[0].scheduled_arrival is None
    assert data.route[0].reported_arrival.isoformat() == "2026-09-23T00:10:00+05:30"
    cached = LiveResult(fetched_at=datetime.now(UTC), data=data)
    assert LiveResult.model_validate_json(cached.model_dump_json()) == cached


@pytest.mark.parametrize(
    "updated,live,expected",
    [
        (0, True, "recent"),
        (601, True, "stale"),
        (None, True, "unknown"),
        (-120, True, "unknown"),
        (0, False, "not_live"),
        (0, None, "unknown"),
    ],
)
def test_freshness_uses_provider_time_not_fetch_time(updated, live, expected):
    now = datetime.now(UTC)
    data = ProviderTrain.model_validate(payload()["data"])
    data.updated_at = now - timedelta(seconds=updated) if updated is not None else None
    data.is_live = live
    result = LiveResult(fetched_at=now, data=data)
    assert railradar.decorate(result, now, True).freshness == expected


def test_fixed_upstream_auth_and_normalization(monkeypatch):
    sample = payload(journey_date=date(2026, 9, 22))
    sample["data"]["extra_private_field"] = "discard me"

    class Opener:
        def open(self, request, timeout):
            assert (
                request.full_url == "https://api.railradar.in/v1/trains/12953/live?date=2026-09-22"
            )
            assert request.get_header("Authorization") == "Bearer test-secret"
            assert timeout == 12
            return io.BytesIO(json.dumps(sample).encode())

    monkeypatch.setattr(railradar, "build_opener", lambda handler: Opener())
    result = railradar.fetch_provider("12953", date(2026, 9, 22), "test-secret")
    assert "extra_private_field" not in result.model_dump()
    assert railradar.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other") is None


@pytest.mark.parametrize(
    "status,expected", [(401, 503), (403, 503), (404, 404), (429, 429), (500, 503), (302, 503)]
)
def test_upstream_errors_are_sanitized(monkeypatch, status, expected):
    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError(
                "https://provider", status, "test-secret", {}, io.BytesIO(b"test-secret")
            )

    monkeypatch.setattr(railradar, "build_opener", lambda handler: Opener())
    with pytest.raises(HTTPException) as caught:
        railradar.fetch_provider("12953", date.today(), "test-secret")
    assert caught.value.status_code == expected
    assert "test-secret" not in str(caught.value.detail)


@pytest.mark.parametrize(
    "case",
    ["invalid_json", "wrong_train", "wrong_date", "unsuccessful", "timeout", "network", "oversize"],
)
def test_bad_provider_payloads_are_rejected(monkeypatch, case):
    class Opener:
        def open(self, *args, **kwargs):
            if case == "timeout":
                raise TimeoutError("test-secret")
            if case == "network":
                raise URLError("test-secret")
            sample = payload()
            if case == "wrong_train":
                sample["data"]["trainNumber"] = "12301"
            if case == "wrong_date":
                sample["data"]["startDate"] = "2020-01-01"
            if case == "unsuccessful":
                sample["success"] = False
            raw = json.dumps(sample).encode()
            if case == "invalid_json":
                raw = b"<html>test-secret</html>"
            if case == "oversize":
                raw = b"x" * (railradar.MAX_RESPONSE_BYTES + 1)
            return io.BytesIO(raw)

    monkeypatch.setattr(railradar, "build_opener", lambda handler: Opener())
    with pytest.raises(HTTPException) as caught:
        railradar.fetch_provider("12953", date.today(), "test-secret")
    assert caught.value.status_code == 503
    assert "test-secret" not in str(caught.value.detail)


def test_any_train_date_cache_and_account_isolation(redis_client, provider, monkeypatch):
    path = "/live/trains/22222?date=2026-09-21"
    first = api(path)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["data"]["train_number"] == "22222"
    assert not first.json()["cached"]
    assert api(path).json()["cached"]
    assert len(provider) == 1
    assert provider[0][1] == date(2026, 9, 21)
    assert api("/live/trains/22222?date=2026-09-22").status_code == 200
    monkeypatch.setenv("RAILRADAR_API_KEY", "different-test-key")
    assert api(path).status_code == 200
    assert len(provider) == 3
    assert not any("test-key" in key for key in redis_client.scan_iter())


@pytest.mark.parametrize("env", ["RAILRADAR_DAILY_LIMIT", "RAILRADAR_MONTHLY_LIMIT"])
def test_shared_budget_stops_new_calls_but_keeps_cache(redis_client, provider, monkeypatch, env):
    monkeypatch.setenv(env, "1")
    assert api("/live/trains/22222").status_code == 200
    assert api("/live/trains/22223").status_code == 429
    assert api("/live/trains/22222").json()["cached"]
    assert len(provider) == 1


def test_outage_preserves_old_source_timestamp_and_cools_down(redis_client, provider, monkeypatch):
    first = api("/live/trains/22222").json()
    keys = list(redis_client.scan_iter(match=f"{realtime.KEY_PREFIX}:railradar:*:train:22222:*"))
    assert len(keys) == 1
    saved = LiveResult.model_validate_json(redis_client.get(keys[0]))
    saved.fetched_at -= timedelta(seconds=301)
    redis_client.set(keys[0], saved.model_dump_json(), ex=86400)
    failures = []

    def fail(*args):
        failures.append(True)
        raise HTTPException(503, "RailRadar temporarily unavailable.")

    monkeypatch.setattr(railradar, "fetch_provider", fail)
    response = api("/live/trains/22222")
    assert response.status_code == 200
    assert response.json()["freshness"] == "stale"
    assert response.json()["warning"]
    assert response.json()["data"]["updated_at"] == first["data"]["updated_at"]
    assert api("/live/trains/22223").status_code == 503
    assert len(failures) == 1


def test_not_found_is_cached_without_blocking_other_trains(redis_client, provider, monkeypatch):
    successful = railradar.fetch_provider
    failures = []

    def sometimes_missing(number, *args):
        if number == "00000":
            failures.append(True)
            raise HTTPException(404, "No data for this journey.")
        return successful(number, *args)

    monkeypatch.setattr(railradar, "fetch_provider", sometimes_missing)
    assert api("/live/trains/00000").status_code == 404
    assert api("/live/trains/00000").status_code == 404
    assert len(failures) == 1
    assert api("/live/trains/22222").status_code == 200


def test_concurrent_lookup_only_spends_one_request(redis_client, provider, monkeypatch):
    entered, release = Event(), Event()
    successful = railradar.fetch_provider

    def blocked(*args):
        entered.set()
        assert release.wait(timeout=5)
        return successful(*args)

    monkeypatch.setattr(railradar, "fetch_provider", blocked)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(railradar.live_train, Response(), "22222", date.today())
        assert entered.wait(timeout=3)
        try:
            assert api("/live/trains/22222?date=" + str(date.today())).status_code == 429
        finally:
            release.set()
        assert first.result().data.train_number == "22222"
    assert len(provider) == 1


def test_redis_outage_fails_closed_without_spending_quota(provider, monkeypatch):
    from redis.exceptions import ConnectionError

    def fail():
        raise ConnectionError("private redis detail")

    monkeypatch.setattr(realtime, "get_redis", fail)
    response = api("/live/trains/22222")
    assert response.status_code == 503
    assert "private" not in response.text
    assert not provider
