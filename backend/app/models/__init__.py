"""PostGIS-backed static network and explicitly synthetic time-series records."""

from datetime import datetime
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    zone: Mapped[str | None] = mapped_column(String(10))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    __table_args__ = (CheckConstraint("lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180"),)


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    train_number: Mapped[str] = mapped_column(String(5), unique=True)
    train_name: Mapped[str] = mapped_column(String(120))
    total_distance_km: Mapped[float] = mapped_column(Float)
    dataset_version: Mapped[str] = mapped_column(String(80))
    geometry_kind: Mapped[str] = mapped_column(String(50))
    geom = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)
    __table_args__ = (CheckConstraint("total_distance_km > 0"),)


class RouteStop(Base):
    __tablename__ = "route_stops"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    station_code: Mapped[str] = mapped_column(ForeignKey("stations.code"))
    arrival_seconds: Mapped[int | None] = mapped_column(Integer)
    departure_seconds: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        UniqueConstraint("route_id", "sequence"),
        UniqueConstraint("route_id", "station_code"),
        CheckConstraint("sequence >= 0 AND distance_km >= 0"),
        CheckConstraint("arrival_seconds IS NOT NULL OR departure_seconds IS NOT NULL"),
        CheckConstraint("arrival_seconds >= 0 AND departure_seconds >= 0"),
        CheckConstraint("departure_seconds >= arrival_seconds"),
    )


class LivePosition(Base):
    __tablename__ = "live_positions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    journey_id: Mapped[UUID] = mapped_column(Uuid)
    train_number: Mapped[str] = mapped_column(ForeignKey("routes.train_number"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    journey_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    distance_km: Mapped[float] = mapped_column(Float)
    delay_minutes: Mapped[float] = mapped_column(Float)
    current_speed_kmh: Mapped[float] = mapped_column(Float)
    last_station: Mapped[str] = mapped_column(ForeignKey("stations.code"))
    next_station: Mapped[str | None] = mapped_column(ForeignKey("stations.code"))
    source: Mapped[str] = mapped_column(String(20), default="simulator")
    __table_args__ = (
        UniqueConstraint("train_number", "journey_id", "timestamp"),
        CheckConstraint("journey_started_at <= timestamp", name="ck_position_journey_start"),
        Index("ix_positions_train_time", "train_number", "timestamp"),
        Index("ix_positions_journey_time", "journey_id", "timestamp"),
        CheckConstraint("lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180"),
        CheckConstraint("distance_km >= 0 AND delay_minutes >= 0"),
        CheckConstraint("current_speed_kmh BETWEEN 0 AND 200"),
        CheckConstraint("source = 'simulator'"),
    )


class Event(Base):
    __tablename__ = "events"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    journey_id: Mapped[UUID] = mapped_column(Uuid)
    train_number: Mapped[str] = mapped_column(ForeignKey("routes.train_number"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_type: Mapped[str] = mapped_column(String(30))
    severity: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default="simulator")
    __table_args__ = (
        Index("ix_events_train_time", "train_number", "timestamp"),
        CheckConstraint(
            "event_type IN ('speed_restriction','unscheduled_stop','congestion','weather')"
        ),
        CheckConstraint("severity BETWEEN 1 AND 3 AND duration_seconds BETWEEN 1 AND 3600"),
        CheckConstraint("source = 'simulator'"),
    )


class HistoricalDelay(Base):
    __tablename__ = "historical_delays"
    id: Mapped[int] = mapped_column(primary_key=True)
    train_number: Mapped[str] = mapped_column(ForeignKey("routes.train_number"))
    station_code: Mapped[str] = mapped_column(ForeignKey("stations.code"))
    day_of_week: Mapped[int] = mapped_column(Integer)
    hour_of_day: Mapped[int] = mapped_column(Integer, server_default="-1")
    avg_delay_minutes: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint(
            "train_number",
            "station_code",
            "day_of_week",
            "hour_of_day",
            name="uq_historical_delay_hour",
        ),
        CheckConstraint("hour_of_day BETWEEN -1 AND 23", name="ck_historical_delay_hour"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6"),
        CheckConstraint("avg_delay_minutes >= 0 AND sample_count > 0"),
    )
