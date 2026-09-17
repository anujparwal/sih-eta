"""Deterministic movement on the timetable, with stochastic synthetic disruptions."""

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4


@dataclass(frozen=True)
class Location:
    distance_km: float
    lat: float
    lon: float
    last_station: str
    next_station: str | None
    speed_kmh: float
    block: tuple | None


def locate(route: dict, stations: dict, clock: float) -> Location:
    """clock is seconds since origin departure; midnight rollovers are already resolved."""
    stops = route["stops"]
    schedule_time = stops[0]["departure_seconds"] + clock
    for index, stop in enumerate(stops):
        station = stations[stop["station_code"]]
        following = stops[index + 1] if index + 1 < len(stops) else None
        if following is None or schedule_time < stop["departure_seconds"]:
            return Location(
                stop["distance_km"],
                station["lat"],
                station["lon"],
                stop["station_code"],
                following["station_code"] if following else None,
                0,
                None,
            )
        if schedule_time < following["arrival_seconds"]:
            duration = following["arrival_seconds"] - stop["departure_seconds"]
            fraction = (schedule_time - stop["departure_seconds"]) / duration
            destination = stations[following["station_code"]]
            segment_km = following["distance_km"] - stop["distance_km"]
            return Location(
                stop["distance_km"] + fraction * segment_km,
                station["lat"] + fraction * (destination["lat"] - station["lat"]),
                station["lon"] + fraction * (destination["lon"] - station["lon"]),
                stop["station_code"],
                following["station_code"],
                segment_km * 3600 / duration,
                (stop["station_code"], following["station_code"], int(fraction * segment_km / 5)),
            )
    raise AssertionError("Route must have at least two stops")


@dataclass
class Disruption:
    event_type: str
    severity: int
    start: float
    duration: int

    @property
    def factor(self) -> float:
        if self.event_type in ("unscheduled_stop", "congestion"):
            return 0
        return 1 - self.severity * 0.2


@dataclass
class Train:
    route: dict
    stations: dict
    started_at: datetime
    rng: random.Random
    event_every: float = 180
    journey_id: str = field(default_factory=lambda: str(uuid4()))
    clock: float = 0
    elapsed: float = 0
    speed: float = 0
    active: Disruption | None = None
    next_event_at: float = field(init=False)

    def __post_init__(self):
        self.next_event_at = self.elapsed + max(20, self.rng.expovariate(1 / self.event_every))

    @property
    def location(self) -> Location:
        return locate(self.route, self.stations, self.clock)

    @property
    def complete(self) -> bool:
        return self.location.next_station is None

    def event_payload(self, disruption: Disruption) -> dict:
        return {
            "id": str(uuid4()),
            "journey_id": self.journey_id,
            "train_number": self.route["train_number"],
            "timestamp": (self.started_at + timedelta(seconds=disruption.start)).isoformat(),
            "event_type": disruption.event_type,
            "severity": disruption.severity,
            "duration_seconds": disruption.duration,
            "source": "simulator",
            "description": f"Synthetic {disruption.event_type.replace('_', ' ')}; "
            "not a reported railway incident.",
        }

    def advance(self, seconds: float, reservations: dict) -> list[dict]:
        old = self.location
        events = []
        if self.active and self.elapsed >= self.active.start + self.active.duration:
            self.active = None
            self.__post_init__()
        if not self.active and old.speed_kmh > 0 and self.elapsed >= self.next_event_at:
            self.active = Disruption(
                self.rng.choice(("speed_restriction", "unscheduled_stop", "congestion", "weather")),
                self.rng.randint(1, 3),
                self.elapsed,
                self.rng.randint(60, 180),
            )
            events.append(self.event_payload(self.active))
        factor = self.active.factor if self.active else 1
        proposed_clock = min(
            self.clock + seconds * factor,
            self.route["stops"][-1]["arrival_seconds"]
            - self.route["stops"][0]["departure_seconds"],
        )
        proposed = locate(self.route, self.stations, proposed_clock)
        owner = reservations.get(proposed.block) if proposed.block else None
        if owner is not None and owner != self.journey_id:
            # Synthetic directional 5 km blocks: never enter another train's occupied block.
            self.speed = 0
        else:
            if old.block != proposed.block and reservations.get(old.block) == self.journey_id:
                reservations.pop(old.block)
            if proposed.block:
                reservations[proposed.block] = self.journey_id
            self.clock = proposed_clock
            self.speed = proposed.speed_kmh * factor
        self.elapsed += seconds
        return events

    def snapshot(self) -> dict:
        location = self.location
        return {
            "id": str(uuid4()),
            "journey_id": self.journey_id,
            "journey_started_at": self.started_at.isoformat(),
            "train_number": self.route["train_number"],
            "timestamp": (self.started_at + timedelta(seconds=self.elapsed)).isoformat(),
            "lat": location.lat,
            "lon": location.lon,
            "distance_km": location.distance_km,
            "delay_minutes": max(0, self.elapsed - self.clock) / 60,
            "current_speed_kmh": self.speed,
            "last_station": location.last_station,
            "next_station": location.next_station,
            "source": "simulator",
        }


class Fleet:
    def __init__(self, dataset: dict, started_at: datetime, seed: int, event_every: float = 180):
        self.stations = {s["code"]: s for s in dataset["stations"]}
        master = random.Random(seed)
        self.trains = [
            Train(
                route, self.stations, started_at, random.Random(master.getrandbits(64)), event_every
            )
            for route in dataset["routes"]
        ]
        self.reservations = {}
        self.now = started_at

    def advance(self, seconds: float) -> list[dict]:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Elapsed seconds must be finite and nonnegative")
        events = []
        # Emit a terminal sample before assigning a new journey on the next caller tick.
        for index, train in enumerate(self.trains):
            if train.complete:
                self.trains[index] = Train(
                    train.route, train.stations, self.now, train.rng, train.event_every
                )
        # Bound each step so dwell boundaries and occupied blocks cannot be skipped.
        while seconds > 1e-9:
            step = min(seconds, 1)
            for train in self.trains:
                if not train.complete:
                    events.extend(train.advance(step, self.reservations))
            self.now += timedelta(seconds=step)
            seconds -= step
        return events
