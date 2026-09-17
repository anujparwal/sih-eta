"""Read endpoints and a polling WebSocket transport for the Phase 3 contract."""

import asyncio
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, WebSocket, WebSocketDisconnect
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_engine, get_session
from app.eta import build_eta, get_route, latest_position, route_stops, train_status
from app.features import latest_positions
from app.models import LivePosition, Route, Station
from app.read_schemas import (
    Arrival,
    FleetStatus,
    JourneyHistory,
    PositionOut,
    StationArrivals,
    TrainETA,
    TrainList,
    TrainSummary,
)

router = APIRouter(tags=["synthetic baseline"])
Database = Annotated[Session, Depends(get_session)]
TrainNumber = Annotated[str, Path(pattern=r"^\d{5}$")]


def utc_now() -> datetime:
    return datetime.now(UTC)


Now = Annotated[datetime, Depends(utc_now)]


def summaries(session: Session, now: datetime) -> list[TrainSummary]:
    positions = {p.train_number: p for p in latest_positions(session, now)}
    result = []
    for route in session.scalars(select(Route).order_by(Route.train_number)):
        stops = route_stops(session, route)
        position = positions.get(route.train_number)
        result.append(
            TrainSummary(
                train_number=route.train_number,
                train_name=route.train_name,
                origin=stops[0].station_code,
                destination=stops[-1].station_code,
                status=train_status(position, now),
                latest_position=PositionOut.model_validate(position) if position else None,
            )
        )
    return result


@router.get("/trains", response_model=TrainList)
def trains(session: Database, now: Now, active_only: bool = False) -> TrainList:
    rows = summaries(session, now)
    return TrainList(
        generated_at=now, trains=[r for r in rows if not active_only or r.status == "active"]
    )


@router.get("/trains/{train_number}/eta", response_model=TrainETA)
def eta(train_number: TrainNumber, session: Database, now: Now) -> TrainETA:
    return build_eta(session, train_number, now)


@router.get("/trains/{train_number}/history", response_model=JourneyHistory)
def history(
    train_number: TrainNumber,
    session: Database,
    now: Now,
    journey_id: UUID | None = None,
    after: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> JourneyHistory:
    get_route(session, train_number)
    latest = latest_position(session, train_number, now)
    selected = journey_id or (latest.journey_id if latest else None)
    query = select(LivePosition).where(
        LivePosition.train_number == train_number,
        LivePosition.journey_id == selected,
        LivePosition.timestamp <= now,
    )
    if journey_id is not None and session.scalar(query.limit(1)) is None:
        raise HTTPException(404, "Journey is not recorded for this train")
    if after is not None:
        query = query.where(LivePosition.timestamp > after)
    rows = list(session.scalars(query.order_by(LivePosition.timestamp).limit(limit + 1)))
    page = rows[:limit]
    return JourneyHistory(
        generated_at=now,
        train_number=train_number,
        journey_id=selected,
        positions=[PositionOut.model_validate(p) for p in page],
        next_after=page[-1].timestamp if len(rows) > limit else None,
    )


@router.get("/stations/{code}/arrivals", response_model=StationArrivals)
def arrivals(
    code: Annotated[str, Path(pattern=r"^[A-Z0-9]{1,10}$")],
    session: Database,
    now: Now,
    include_stale: bool = False,
) -> StationArrivals:
    if session.scalar(select(Station.id).where(Station.code == code)) is None:
        raise HTTPException(404, "Station is not in the seeded network")
    result = []
    for route in session.scalars(select(Route).order_by(Route.train_number)):
        snapshot = build_eta(session, route.train_number, now, with_features=False)
        if snapshot.status != "active" and not (include_stale and snapshot.status == "stale"):
            continue
        for stop in snapshot.stations:
            if stop.station_code == code:
                result.append(
                    Arrival(
                        **stop.model_dump(),
                        train_number=route.train_number,
                        train_name=route.train_name,
                        journey_id=snapshot.journey_id,
                        as_of=snapshot.as_of,
                        status=snapshot.status,
                        timing_basis=snapshot.timing_basis,
                    )
                )
    return StationArrivals(
        generated_at=now,
        station_code=code,
        arrivals=sorted(result, key=lambda a: (a.eta, a.train_number)),
    )


@router.get("/control/fleet-status", response_model=FleetStatus)
def fleet_status(session: Database, now: Now) -> FleetStatus:
    rows = summaries(session, now)
    delays = [r.latest_position.delay_minutes for r in rows if r.status == "active"]
    return FleetStatus(
        generated_at=now,
        trains=rows,
        total_trains=len(rows),
        active_trains=len(delays),
        stale_trains=sum(r.status == "stale" for r in rows),
        completed_trains=sum(r.status == "completed" for r in rows),
        no_data_trains=sum(r.status == "no_data" for r in rows),
        delayed_active_trains=sum(d > 0 for d in delays),
        mean_active_delay_minutes=sum(delays) / len(delays) if delays else None,
        max_active_delay_minutes=max(delays) if delays else None,
    )


def socket_snapshot(train_number: str) -> TrainETA:
    # A fresh short-lived session per poll; no transaction/connection held across awaits.
    with Session(get_engine()) as session:
        return build_eta(session, train_number, utc_now())


@router.websocket("/ws/trains/{train_number}")
async def websocket_eta(websocket: WebSocket, train_number: TrainNumber) -> None:
    await websocket.accept()
    previous = None

    async def disconnected():
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

    receiver = asyncio.create_task(disconnected())
    try:
        while True:
            snapshot = await run_in_threadpool(socket_snapshot, train_number)
            signature = snapshot.model_dump_json(exclude={"generated_at"})
            if signature != previous:
                await websocket.send_json(
                    {"type": "eta_update", "data": snapshot.model_dump(mode="json")}
                )
                previous = signature
            # Text/binary input is ignored. Receiving concurrently detects idle disconnects
            # without allowing client messages to accelerate database polling.
            done, _ = await asyncio.wait({receiver}, timeout=1)
            if done:
                await receiver
                break
    except WebSocketDisconnect:
        pass
    except HTTPException as error:
        await websocket.send_json(
            {"type": "error", "code": error.status_code, "detail": error.detail}
        )
        await websocket.close(code=1008)
    except SQLAlchemyError:
        await websocket.send_json(
            {"type": "error", "code": 503, "detail": "Telemetry store unavailable"}
        )
        await websocket.close(code=1011)
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)
