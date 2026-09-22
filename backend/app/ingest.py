"""Validated, idempotent ingestion; publish committed updates through Redis."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Event, LivePosition, Route, RouteStop, Station
from app.realtime import publish_committed
from app.schemas import EventIn, IngestResult, PositionIn

router = APIRouter(
    prefix="/ingest",
    tags=["synthetic telemetry"],
    responses={
        401: {"description": "Missing or invalid ingestion credentials when INGEST_API_KEY is set"},
        413: {"description": "Request body too large"},
        429: {"description": "Shared ingestion rate limit exceeded"},
        503: {"description": "Storage or realtime service unavailable; retry the same UUID"},
    },
)
Database = Annotated[Session, Depends(get_session)]


def lock_route(session: Session, train_number: str) -> Route:
    # Serialize each train's writes so concurrent samples cannot bypass ordering checks.
    route = session.scalar(
        select(Route).where(Route.train_number == train_number).with_for_update()
    )
    if route is None:
        raise HTTPException(404, "Train is not in the seeded network")
    return route


def duplicate(session: Session, model, payload) -> bool:
    existing = session.get(model, payload.id)
    if existing is None:
        return False
    if any(getattr(existing, key) != value for key, value in payload.model_dump().items()):
        raise HTTPException(409, "ID already exists with different content")
    return True


def save(session: Session, record) -> None:
    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Sample conflicts with an existing record") from None


def validate_location(session: Session, route: Route, payload: PositionIn) -> None:
    stops = list(
        session.scalars(
            select(RouteStop).where(RouteStop.route_id == route.id).order_by(RouteStop.sequence)
        )
    )
    # Both legacy-anchor inference and future arrivals must fit datetime arithmetic.
    # This is a representability check, not an invented operational delay threshold.
    try:
        horizon = timedelta(
            seconds=stops[-1].arrival_seconds - stops[0].departure_seconds,
            minutes=payload.delay_minutes,
        )
        payload.timestamp - horizon
        payload.timestamp + horizon
    except OverflowError:
        raise HTTPException(
            422, "Timestamp and delay exceed the supported timetable range"
        ) from None
    index = next(
        (i for i, stop in enumerate(stops) if stop.station_code == payload.last_station), None
    )
    if index is None:
        raise HTTPException(422, "last_station is not on this route")
    last = stops[index]
    following = stops[index + 1] if index + 1 < len(stops) else None
    if payload.next_station != (following.station_code if following else None):
        raise HTTPException(422, "Station pair must be adjacent and in route order")
    end = following.distance_km if following else last.distance_km
    if not last.distance_km <= payload.distance_km <= end:
        raise HTTPException(422, "Distance is outside the reported route segment")
    station = session.scalar(select(Station).where(Station.code == last.station_code))
    lat, lon = station.lat, station.lon
    if following:
        destination = session.scalar(select(Station).where(Station.code == following.station_code))
        fraction = (payload.distance_km - last.distance_km) / (end - last.distance_km)
        lat += fraction * (destination.lat - lat)
        lon += fraction * (destination.lon - lon)
    # Data uses schematic station connectors, not surveyed tracks. Tolerance ~100 m.
    if abs(payload.lat - lat) > 0.001 or abs(payload.lon - lon) > 0.001:
        raise HTTPException(422, "Coordinates do not match the synthetic route position")
    if following is None and payload.current_speed_kmh != 0:
        raise HTTPException(422, "An arrived train must have zero speed")


@router.post("/position", response_model=IngestResult, status_code=201)
def ingest_position(payload: PositionIn, response: Response, session: Database) -> IngestResult:
    route = lock_route(session, payload.train_number)
    if duplicate(session, LivePosition, payload):
        session.commit()
        publish_committed(session, payload)
        response.status_code = 200
        return IngestResult(id=payload.id, status="duplicate")
    validate_location(session, route, payload)
    previous = session.scalar(
        select(LivePosition)
        .where(
            LivePosition.train_number == payload.train_number,
            LivePosition.journey_id == payload.journey_id,
        )
        .order_by(LivePosition.timestamp.desc())
        .limit(1)
    )
    if previous and (
        payload.timestamp <= previous.timestamp or payload.distance_km < previous.distance_km
    ):
        raise HTTPException(409, "Journey samples must advance in time without moving backwards")
    if previous:
        if payload.journey_started_at != previous.journey_started_at:
            raise HTTPException(409, "Journey start must remain unchanged within a journey")
        elapsed = (payload.timestamp - previous.timestamp).total_seconds()
        if payload.distance_km - previous.distance_km > elapsed * 200 / 3600 + 0.01:
            raise HTTPException(422, "Distance jump exceeds the maximum supported train speed")
    save(
        session,
        LivePosition(
            **payload.model_dump(),
            geom=WKTElement(f"POINT({payload.lon} {payload.lat})", srid=4326),
        ),
    )
    publish_committed(session, payload)
    return IngestResult(id=payload.id, status="created")


@router.post("/event", response_model=IngestResult, status_code=201)
def ingest_event(payload: EventIn, response: Response, session: Database) -> IngestResult:
    lock_route(session, payload.train_number)
    if duplicate(session, Event, payload):
        session.commit()
        publish_committed(session, payload)
        response.status_code = 200
        return IngestResult(id=payload.id, status="duplicate")
    save(session, Event(**payload.model_dump()))
    publish_committed(session, payload)
    return IngestResult(id=payload.id, status="created")
