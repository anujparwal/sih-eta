import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models import Base
from app.seed import seed_network


def test_migration_round_trip_preserves_postgis_and_matches_models(db_engine):
    # db_engine requires an explicitly configured *_test database. Never use the app database.
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = os.environ["TEST_DATABASE_URL"]
    try:
        command.downgrade(config, "base")
        assert not set(Base.metadata.tables).intersection(inspect(db_engine).get_table_names())
        with db_engine.connect() as connection:
            assert connection.scalar(text("SELECT postgis_version()"))
        command.upgrade(config, "head")
        command.check(config)
        assert set(Base.metadata.tables).issubset(inspect(db_engine).get_table_names())
    finally:
        command.upgrade(config, "head")
        with Session(db_engine) as session, session.begin():
            seed_network(session)
