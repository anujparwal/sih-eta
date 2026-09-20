"""Build as-of features and observed next-station targets, with journey-level splits."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby
from uuid import UUID

from app.features import feature_values
from app.models import Event, LivePosition, RouteStop
from app.read_schemas import Features
from app.schemas import EventIn, PositionIn
from app.seed import load_dataset


@dataclass
class Example:
    train_number: str
    journey_id: UUID
    journey_started_at: datetime
    journey_ended_at: datetime
    label_at: datetime
    station_code: str
    scheduled_arrival: datetime
    features: Features
    target: float


def objects(data: dict) -> tuple[list[LivePosition], list[Event]]:
    positions = [
        LivePosition(**PositionIn.model_validate(p).model_dump()) for p in data["positions"]
    ]
    events = [Event(**EventIn.model_validate(e).model_dump()) for e in data["events"]]
    return positions, events


def observed_arrivals(positions: list[LivePosition], stops: list[RouteStop]) -> dict:
    """First observation after a station crossing; reject skipped stations and legacy anchors."""
    arrivals = {}
    by_code = {s.station_code: s for s in stops}
    for previous, point in zip(positions, positions[1:]):
        if point.journey_started_at is None or point.last_station == previous.last_station:
            continue
        if previous.next_station != point.last_station:
            continue
        stop = by_code[point.last_station]
        scheduled_seconds = stop.arrival_seconds - stops[0].departure_seconds
        target = (point.timestamp - point.journey_started_at).total_seconds() / 60
        target -= scheduled_seconds / 60
        # Never pretend a sparse crossing measurement is a precise arrival observation.
        if (point.timestamp - previous.timestamp).total_seconds() > 120:
            continue
        if target >= 0:
            arrivals.setdefault(point.last_station, (point.timestamp, target))
    return arrivals


def examples_from_records(data: dict) -> list[Example]:
    positions, events = objects(data)
    routes = {
        r["train_number"]: [RouteStop(**s) for s in r["stops"]] for r in load_dataset()["routes"]
    }
    journeys, journey_events = defaultdict(list), defaultdict(list)
    for point in positions:
        journeys[(point.train_number, point.journey_id)].append(point)
    for event in events:
        journey_events[(event.train_number, event.journey_id)].append(event)
    targets, ended = {}, {}
    for key, points in journeys.items():
        points.sort(key=lambda p: p.timestamp)
        if not points or points[-1].next_station is not None:
            continue  # Only completed journeys have a known separation boundary.
        if any(p.journey_started_at != points[0].journey_started_at for p in points):
            raise ValueError("Journey start must be immutable")
        targets[key] = observed_arrivals(points, routes[key[0]])
        ended[key] = points[-1].timestamp
    latest, reached = {}, {}
    examples = []
    for _, batch in groupby(
        sorted(positions, key=lambda p: (p.timestamp, p.train_number, str(p.id))),
        key=lambda p: p.timestamp,
    ):
        batch = list(batch)
        for point in batch:
            latest[point.train_number] = point
        for point in batch:
            key = (point.train_number, point.journey_id)
            if key not in targets or point.next_station not in targets[key]:
                continue
            label_at, target = targets[key][point.next_station]
            if label_at <= point.timestamp or point.journey_started_at is None:
                continue
            stops = routes[point.train_number]
            current = next(s for s in stops if s.station_code == point.last_station)
            upcoming = next(s for s in stops if s.station_code == point.next_station)
            reach_key = (*key, point.last_station)
            if point.distance_km <= current.distance_km + 0.01:
                reached.setdefault(reach_key, point.timestamp)
            reached_at = reached.get(reach_key)
            if current.sequence == stops[0].sequence:
                reached_at = point.journey_started_at
            # HistoricalDelay has no availability timestamp: using a present-day aggregate
            # for old samples leaks future arrivals. It is excluded from model inputs.
            features = feature_values(
                point, upcoming, reached_at, None, journey_events[key], list(latest.values())
            )
            examples.append(
                Example(
                    point.train_number,
                    point.journey_id,
                    point.journey_started_at,
                    ended[key],
                    label_at,
                    point.next_station,
                    point.journey_started_at
                    + timedelta(seconds=upcoming.arrival_seconds - stops[0].departure_seconds),
                    features,
                    target,
                )
            )
    return examples


def chronological_split(
    examples: list[Example],
) -> tuple[list[Example], list[Example], list[Example]]:
    starts = sorted({e.journey_started_at for e in examples})
    if len(starts) < 6:
        raise ValueError("Need at least six distinct journey start times")
    validation_at, test_at = starts[int(len(starts) * 0.65)], starts[int(len(starts) * 0.82)]
    train = [e for e in examples if e.journey_ended_at < validation_at]
    validation = [
        e
        for e in examples
        if e.journey_started_at >= validation_at and e.journey_ended_at < test_at
    ]
    test = [e for e in examples if e.journey_started_at >= test_at]
    if not all((train, validation, test)):
        raise ValueError("Insufficient completed journeys after purging split boundaries")
    return train, validation, test
