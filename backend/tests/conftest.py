import asyncio
import os
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import get_session
from app.main import app
from app.seed import load_dataset, seed_network


def pytest_addoption(parser):
    parser.addoption(
        "--require-services",
        action="store_true",
        help="Fail before collection if PostGIS/Redis integration test URLs are missing",
    )


def pytest_configure(config):
    if config.getoption("--require-services", default=False):
        missing = [key for key in ("TEST_DATABASE_URL", "TEST_REDIS_URL") if not os.getenv(key)]
        if missing:
            raise pytest.UsageError("Full suite requires " + ", ".join(missing))


@pytest.fixture(scope="session")
def dataset():
    return load_dataset()


@pytest.fixture(scope="session")
def db_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL/PostGIS database")
    if not (make_url(url).database or "").endswith("_test"):
        raise ValueError("Integration database name must end with _test")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_engine(url)
    with Session(engine) as session, session.begin():
        seed_network(session)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    with db_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:

            def override():
                yield session

            app.dependency_overrides[get_session] = override
            try:
                yield session
            finally:
                app.dependency_overrides.pop(get_session, None)
        transaction.rollback()


@pytest.fixture
def request_api(redis_client):
    def request(method, path, payload):
        async def send():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.request(method, path, json=payload)

        return asyncio.run(send())

    return request


@pytest.fixture
def redis_client(monkeypatch):
    from uuid import uuid4

    from redis import Redis

    from app import realtime

    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_REDIS_URL to Redis database 15 for realtime integration tests")
    from urllib.parse import urlparse

    if urlparse(url).path != "/15":
        raise ValueError("TEST_REDIS_URL must use dedicated Redis database 15")
    client = Redis.from_url(url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
    client.ping()
    prefix = f"sih-eta-test:{uuid4()}"
    monkeypatch.setattr(realtime, "KEY_PREFIX", prefix)
    monkeypatch.setattr(realtime, "get_redis", lambda: client)
    monkeypatch.setattr(realtime, "redis_url", lambda: url)
    try:
        yield client
    finally:
        keys = list(client.scan_iter(match=f"{prefix}:*"))
        if keys:
            client.delete(*keys)
        client.close()
