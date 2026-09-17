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


def test_phase_three_upgrade_preserves_legacy_data_and_protects_hourly_data(db_engine):
    from uuid import uuid4

    import pytest
    from sqlalchemy.exc import DBAPIError

    sample_id, journey_id = uuid4(), uuid4()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = os.environ["TEST_DATABASE_URL"]
    try:
        command.downgrade(config, "612d6a4111d6")
        with db_engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO live_positions
                (id, journey_id, train_number, timestamp, lat, lon, geom, distance_km,
                 delay_minutes, current_speed_kmh, last_station, next_station, source)
                SELECT :id, :journey, '12301', '2026-01-01T00:00:00Z', lat, lon, geom,
                       0, 0, 0, 'HWH', 'DKAE', 'simulator' FROM stations WHERE code='HWH'
            """),
                {"id": sample_id, "journey": journey_id},
            )
            connection.execute(
                text("""
                INSERT INTO historical_delays
                (train_number, station_code, day_of_week, avg_delay_minutes, sample_count)
                VALUES ('12301', 'DKAE', 0, 12.5, 8)
            """)
            )
        command.upgrade(config, "head")
        with db_engine.begin() as connection:
            row = connection.execute(
                text("SELECT journey_started_at, journey_id FROM live_positions WHERE id=:id"),
                {"id": sample_id},
            ).one()
            assert row == (None, journey_id)
            assert connection.execute(
                text("SELECT hour_of_day, avg_delay_minutes, sample_count FROM historical_delays")
            ).one() == (-1, 12.5, 8)
            connection.execute(
                text("""
                INSERT INTO historical_delays
                (train_number, station_code, day_of_week, hour_of_day,
                 avg_delay_minutes, sample_count)
                VALUES ('12301', 'DKAE', 0, 9, 15, 3)
            """)
            )
        with pytest.raises(DBAPIError, match="Export and remove hourly history"):
            command.downgrade(config, "612d6a4111d6")
        with db_engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM historical_delays")) == 2
    finally:
        command.upgrade(config, "head")
        with db_engine.begin() as connection:
            connection.execute(text("DELETE FROM live_positions WHERE id=:id"), {"id": sample_id})
            connection.execute(
                text(
                    "DELETE FROM historical_delays WHERE train_number='12301' "
                    "AND station_code='DKAE' AND day_of_week=0"
                )
            )
