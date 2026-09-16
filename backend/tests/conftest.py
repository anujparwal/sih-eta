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
def request_api():
    def request(method, path, payload):
        async def send():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.request(method, path, json=payload)

        return asyncio.run(send())

    return request
