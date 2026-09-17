"""Reproducible features as of a telemetry sample, never using later observations."""

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, HistoricalDelay, LivePosition, RouteStop
from app.read_schemas import Features

IST = ZoneInfo("Asia/Kolkata")


def latest_positions(session: Session, as_of: datetime) -> list[LivePosition]:
    """Select a single current journey per train BEFORE applying section/age filters."""
    return list(
        session.scalars(
            select(LivePosition)
            .where(LivePosition.timestamp <= as_of)
            .distinct(LivePosition.train_number)
            .order_by(
                LivePosition.train_number, LivePosition.timestamp.desc(), LivePosition.id.desc()
            )
        )
    )


def distance_km(a: LivePosition, b: LivePosition) -> float:
    """Great-circle distance on schematic station connectors, not track distance."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    chord = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, chord))))


def congestion_count(position: LivePosition, others: list[LivePosition], radius_km: float) -> int:
    if position.next_station is None:
        return 0
    section = {position.last_station, position.next_station}
    return sum(
        other.train_number != position.train_number
        and other.next_station is not None
        and {other.last_station, other.next_station} == section
        and position.timestamp - timedelta(minutes=10) <= other.timestamp <= position.timestamp
        and distance_km(position, other) <= radius_km
        for other in others
    )


def active_events(position: LivePosition, events: list[Event]) -> list[Event]:
    # Simulator disruptions are scoped to the train's entire journey, not fixed track incidents.
    return [
        event
        for event in events
        if position.next_station is not None
        and event.train_number == position.train_number
        and event.journey_id == position.journey_id
        and event.timestamp
        <= position.timestamp
        < event.timestamp + timedelta(seconds=event.duration_seconds)
    ]


def compute_features(
    session: Session,
    position: LivePosition,
    stops: list[RouteStop],
    radius_km: float = 5,
) -> Features:
    current = next(stop for stop in stops if stop.station_code == position.last_station)
    upcoming = next((stop for stop in stops if stop.station_code == position.next_station), None)
    # A station observation approximates arrival to the sampling interval. Do not pretend
    # that the first sample halfway down a segment is an observed station arrival.
    reached_at = session.scalar(
        select(LivePosition.timestamp)
        .where(
            LivePosition.train_number == position.train_number,
            LivePosition.journey_id == position.journey_id,
            LivePosition.timestamp <= position.timestamp,
            LivePosition.last_station == position.last_station,
            LivePosition.distance_km <= current.distance_km + 0.01,
        )
        .order_by(LivePosition.timestamp)
        .limit(1)
    )
    if current.sequence == stops[0].sequence and position.journey_started_at is not None:
        reached_at = position.journey_started_at
    local = position.timestamp.astimezone(IST)
    history = (
        session.scalar(
            select(HistoricalDelay).where(
                HistoricalDelay.train_number == position.train_number,
                HistoricalDelay.station_code == position.next_station,
                HistoricalDelay.day_of_week == local.weekday(),
                HistoricalDelay.hour_of_day == local.hour,
            )
        )
        if upcoming
        else None
    )
    events = active_events(
        position,
        list(
            session.scalars(
                select(Event).where(
                    Event.train_number == position.train_number,
                    Event.journey_id == position.journey_id,
                    Event.timestamp <= position.timestamp,
                    Event.timestamp > position.timestamp - timedelta(hours=1),
                )
            )
        ),
    )
    return feature_values(
        position,
        upcoming,
        reached_at,
        history,
        events,
        latest_positions(session, position.timestamp),
        radius_km,
    )


def feature_values(
    position: LivePosition,
    upcoming: RouteStop | None,
    reached_at: datetime | None,
    history: HistoricalDelay | None,
    events: list[Event],
    others: list[LivePosition],
    radius_km: float = 5,
) -> Features:
    """Pure arithmetic over an as-of context, shared by API and future model code."""
    local = position.timestamp.astimezone(IST)
    events = active_events(position, events)
    missing = []
    if reached_at is None:
        missing.append("minutes_since_last_station")
    if history is None:
        missing.append("historical_avg_delay_minutes")
    return Features(
        as_of=position.timestamp,
        minutes_since_last_station=(position.timestamp - reached_at).total_seconds() / 60
        if reached_at
        else None,
        distance_remaining_next_station_km=max(0, upcoming.distance_km - position.distance_km)
        if upcoming
        else 0,
        current_delay_minutes=position.delay_minutes,
        historical_avg_delay_minutes=history.avg_delay_minutes if history else None,
        historical_sample_count=history.sample_count if history else 0,
        historical_station_code=position.next_station,
        historical_day_of_week=local.weekday(),
        historical_hour_of_day=local.hour,
        active_event_count=len(events),
        active_event_severity_sum=sum(e.severity for e in events),
        active_event_max_severity=max((e.severity for e in events), default=0),
        congestion_index=congestion_count(position, others, radius_km),
        congestion_radius_km=radius_km,
        missing=missing,
    )
