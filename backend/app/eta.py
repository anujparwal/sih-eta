"""Independent carryover baseline plus an optional next-station model prediction."""

from datetime import datetime, timedelta

import xgboost as xgb
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features import compute_features
from app.inference import get_predictor
from app.models import LivePosition, Route, RouteStop, Station
from app.read_schemas import StationETA, Status, TimingBasis, TrainETA

STALE_AFTER_SECONDS = 30


def get_route(session: Session, train_number: str) -> Route:
    route = session.scalar(select(Route).where(Route.train_number == train_number))
    if route is None:
        raise HTTPException(404, "Train is not in the seeded network")
    return route


def route_stops(session: Session, route: Route) -> list[RouteStop]:
    return list(
        session.scalars(
            select(RouteStop).where(RouteStop.route_id == route.id).order_by(RouteStop.sequence)
        )
    )


def latest_position(session: Session, train_number: str, now: datetime) -> LivePosition | None:
    return session.scalar(
        select(LivePosition)
        .where(
            LivePosition.train_number == train_number,
            LivePosition.timestamp <= now,
        )
        .order_by(LivePosition.timestamp.desc(), LivePosition.id.desc())
        .limit(1)
    )


def train_status(position: LivePosition | None, now: datetime) -> Status:
    if position is None:
        return "no_data"
    if position.next_station is None:
        return "completed"
    return "stale" if (now - position.timestamp).total_seconds() > STALE_AFTER_SECONDS else "active"


def journey_anchor(
    session: Session, position: LivePosition, stops: list[RouteStop]
) -> tuple[datetime, TimingBasis]:
    if position.journey_started_at is not None:
        return position.journey_started_at, "provided"
    first = session.scalar(
        select(LivePosition)
        .where(
            LivePosition.train_number == position.train_number,
            LivePosition.journey_id == position.journey_id,
            LivePosition.timestamp <= position.timestamp,
        )
        .order_by(LivePosition.timestamp)
        .limit(1)
    )
    index = next(i for i, stop in enumerate(stops) if stop.station_code == first.last_station)
    last = stops[index]
    # Legacy mid-dwell observations are ambiguous: choose arrival, explicitly mark inference.
    nominal = last.arrival_seconds if last.arrival_seconds is not None else last.departure_seconds
    if first.next_station and first.distance_km > last.distance_km:
        following = stops[index + 1]
        fraction = (first.distance_km - last.distance_km) / (
            following.distance_km - last.distance_km
        )
        nominal = last.departure_seconds + fraction * (
            following.arrival_seconds - last.departure_seconds
        )
    elapsed = nominal - stops[0].departure_seconds + first.delay_minutes * 60
    return first.timestamp - timedelta(seconds=elapsed), "inferred_from_first_position"


def build_eta(
    session: Session, train_number: str, now: datetime, *, with_features: bool = True
) -> TrainETA:
    route = get_route(session, train_number)
    position = latest_position(session, train_number, now)
    common = dict(generated_at=now, train_number=train_number, status=train_status(position, now))
    if position is None:
        return TrainETA(
            **common,
            journey_id=None,
            position_id=None,
            as_of=None,
            journey_started_at=None,
            timing_basis="unavailable",
            current_delay_minutes=None,
            features=None,
            stations=[],
            ml_status="no_next_station",
        )
    stops = route_stops(session, route)
    anchor, basis = journey_anchor(session, position, stops)
    current = next(stop for stop in stops if stop.station_code == position.last_station)
    names = dict(session.execute(select(Station.code, Station.name)).all())
    features = compute_features(session, position, stops)
    explanation = None
    predictor = get_predictor()
    ml_status = "unavailable"
    if not position.next_station:
        ml_status = "no_next_station"
    elif basis != "provided":
        ml_status = "legacy_timing"
    elif predictor is not None:
        try:
            explanation = predictor.explain(features)
            ml_status = "ready" if explanation else "outside_training_domain"
        except (ValueError, OverflowError, xgb.core.XGBoostError):
            ml_status = "prediction_error"
    predictions = []
    for stop in stops:
        if stop.sequence <= current.sequence:
            continue
        scheduled = anchor + timedelta(seconds=stop.arrival_seconds - stops[0].departure_seconds)
        baseline = scheduled + timedelta(minutes=position.delay_minutes)
        prediction = None
        ml_eta = None
        if explanation is not None and stop.station_code == position.next_station:
            prediction = explanation.model_copy(deep=True)
            minimum = max(0, (position.timestamp - scheduled).total_seconds() / 60)
            bounded = max(minimum, prediction.predicted_delay_minutes)
            prediction.clipping_adjustment_minutes += bounded - prediction.predicted_delay_minutes
            prediction.predicted_delay_minutes = bounded
            try:
                ml_eta = scheduled + timedelta(minutes=bounded)
            except OverflowError:
                prediction = None
                ml_status = "prediction_error"
        predictions.append(
            StationETA(
                station_code=stop.station_code,
                station_name=names[stop.station_code],
                sequence=stop.sequence,
                distance_remaining_km=max(0, stop.distance_km - position.distance_km),
                scheduled_arrival=scheduled,
                baseline_eta=baseline,
                eta=ml_eta or baseline,
                ml_eta=ml_eta,
                eta_baseline_minutes=(baseline - position.timestamp).total_seconds() / 60,
                eta_ml_minutes=(ml_eta - position.timestamp).total_seconds() / 60
                if ml_eta
                else None,
                predicted_delay_minutes=prediction.predicted_delay_minutes if prediction else None,
                explanation=prediction,
                prediction_method="xgboost_next_station" if ml_eta else "current_delay_carryover",
                model_version=predictor.version if ml_eta else None,
            )
        )
    return TrainETA(
        **common,
        journey_id=position.journey_id,
        position_id=position.id,
        as_of=position.timestamp,
        journey_started_at=anchor,
        timing_basis=basis,
        current_delay_minutes=position.delay_minutes,
        features=features if with_features else None,
        ml_status=ml_status,
        eta_baseline_minutes=predictions[0].eta_baseline_minutes if predictions else None,
        eta_ml_minutes=predictions[0].eta_ml_minutes if predictions else None,
        stations=predictions,
    )
