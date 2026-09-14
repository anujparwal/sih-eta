"""Health semantics must distinguish a running process from working dependencies."""

import asyncio

import httpx
import pytest

from app import main


def get(path: str) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


async def available() -> None:
    pass


async def unavailable() -> None:
    raise ConnectionError("secret-password-must-not-leak")


def test_liveness_does_not_require_external_services(monkeypatch):
    monkeypatch.setattr(main, "check_postgres", unavailable)
    monkeypatch.setattr(main, "check_redis", unavailable)
    response = get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("postgres_ok", "redis_ok"), [(True, True), (False, True), (True, False), (False, False)]
)
def test_readiness_reports_each_dependency(monkeypatch, postgres_ok, redis_ok):
    monkeypatch.setattr(main, "check_postgres", available if postgres_ok else unavailable)
    monkeypatch.setattr(main, "check_redis", available if redis_ok else unavailable)
    response = get("/ready")
    assert response.status_code == (200 if postgres_ok and redis_ok else 503)
    assert response.json() == {
        "status": "ok" if postgres_ok and redis_ok else "unavailable",
        "dependencies": {
            "postgres": "ok" if postgres_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
    }
    assert "secret-password" not in response.text


def test_openapi_contains_only_infrastructure_routes():
    assert set(get("/openapi.json").json()["paths"]) == {"/health", "/ready"}
