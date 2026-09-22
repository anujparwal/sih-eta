"""Managed-host configuration and ingestion credentials preserve local behavior."""

import asyncio
import subprocess
from unittest.mock import AsyncMock

import httpx
import pytest

from app import main, start
from app.database import database_url


def request(method, path, **kwargs):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_managed_database_url_preserves_credentials_and_tls(monkeypatch, scheme):
    monkeypatch.setenv("DATABASE_URL", f"{scheme}://demo:p%40ss%3Aword@db:5433/eta?sslmode=require")
    url = database_url()
    assert url.drivername == "postgresql+psycopg"
    assert (url.username, url.password, url.host, url.port, url.database) == (
        "demo",
        "p@ss:word",
        "db",
        5433,
        "eta",
    )
    assert url.query == {"sslmode": "require"}


def test_local_database_configuration_and_invalid_managed_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for key, value in {
        "USER": "demo",
        "PASSWORD": "p@ss",
        "HOST": "db",
        "PORT": "5433",
        "DB": "eta",
    }.items():
        monkeypatch.setenv(f"POSTGRES_{key}", value)
    url = database_url()
    assert (url.username, url.password, url.host, url.port, url.database) == (
        "demo",
        "p@ss",
        "db",
        5433,
        "eta",
    )
    monkeypatch.setenv("DATABASE_URL", "sqlite:///demo")
    with pytest.raises(ValueError, match="PostgreSQL"):
        database_url()


def test_readiness_uses_the_managed_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://demo:p%40ss@db/eta?sslmode=require")
    connection = AsyncMock()
    connection.execute.return_value.fetchone.return_value = (1,)
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(main.psycopg.AsyncConnection, "connect", connect)
    asyncio.run(main.check_postgres())
    connect.assert_awaited_once_with(
        "postgresql://demo:p%40ss@db/eta?sslmode=require", connect_timeout=3
    )


@pytest.mark.parametrize("port", [None, "10000"])
def test_start_migrates_and_seeds_before_serving(monkeypatch, port):
    calls = []
    if port is None:
        monkeypatch.delenv("PORT", raising=False)
    else:
        monkeypatch.setenv("PORT", port)
    monkeypatch.setattr(start.subprocess, "run", lambda args, **kw: calls.append((args, kw)))
    monkeypatch.setattr(start.os, "execvp", lambda program, args: calls.append((program, args)))
    start.main()
    assert calls[:2] == [
        (["alembic", "upgrade", "head"], {"check": True}),
        (["python", "-m", "app.seed"], {"check": True}),
    ]
    assert calls[2] == (
        "uvicorn",
        [
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port or "8000",
            "--no-proxy-headers",
        ],
    )


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_start_rejects_invalid_port_before_migration(monkeypatch, port):
    monkeypatch.setenv("PORT", port)
    monkeypatch.setattr(start.subprocess, "run", lambda *a, **k: pytest.fail("must not migrate"))
    with pytest.raises(ValueError):
        start.main()


@pytest.mark.parametrize("failed_command", ["alembic", "python"])
def test_start_never_serves_after_migration_or_seed_failure(monkeypatch, failed_command):
    def run(args, **kwargs):
        if args[0] == failed_command:
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(start.subprocess, "run", run)
    monkeypatch.setattr(start.os, "execvp", lambda *a: pytest.fail("must not serve"))
    with pytest.raises(subprocess.CalledProcessError):
        start.main()


@pytest.mark.parametrize("path", ["/ingest/position", "/ingest/event"])
@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic deployment-test-key"])
def test_bad_ingest_credentials_rejected_before_storage(monkeypatch, path, authorization):
    monkeypatch.setenv("INGEST_API_KEY", "deployment-test-key")
    monkeypatch.setattr("app.realtime.check_rate", lambda *a: pytest.fail("must not touch Redis"))
    headers = {} if authorization is None else {"Authorization": authorization}
    response = request("POST", path, headers=headers, content=b"not even JSON")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "deployment-test-key" not in response.text
    assert request("GET", "/health").status_code == 200
    assert request("GET", "/network").status_code == 200


@pytest.mark.parametrize("path", ["/ingest/position", "/ingest/event"])
@pytest.mark.parametrize("key", ["", "deployment-test-key"])
def test_authorized_or_local_ingestion_reaches_validation(monkeypatch, path, key):
    monkeypatch.setenv("INGEST_API_KEY", key)
    calls = []
    monkeypatch.setattr("app.realtime.check_rate", lambda peer: (calls.append(peer) or True, 0))
    response = request(
        "POST", path, json={}, headers={"Authorization": f"Bearer {key}"} if key else {}
    )
    assert response.status_code == 422  # The real endpoint validates the now-authorized body.
    assert len(calls) == 1
