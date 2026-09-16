"""Assert a two-minute end-to-end run produced coherent trails for all six trains."""

import argparse
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Event, LivePosition, Route


def verify(session: Session, since: datetime, minimum_samples: int = 20) -> list[dict]:
    summaries = []
    routes = list(session.scalars(select(Route).order_by(Route.train_number)))
    if len(routes) != 6:
        raise AssertionError(f"Expected six routes, found {len(routes)}")
    for route in routes:
        samples = list(
            session.scalars(
                select(LivePosition)
                .where(
                    LivePosition.train_number == route.train_number,
                    LivePosition.timestamp >= since,
                )
                .order_by(LivePosition.timestamp)
            )
        )
        if len(samples) < minimum_samples:
            raise AssertionError(f"{route.train_number}: only {len(samples)} samples")
        if len({row.journey_id for row in samples}) != 1:
            raise AssertionError(
                "Run verification on a fresh two-minute interval, without restarts"
            )
        distance = samples[-1].distance_km - samples[0].distance_km
        if distance <= 0 or (samples[-1].timestamp - samples[0].timestamp).total_seconds() < 110:
            raise AssertionError(f"{route.train_number}: no moving two-minute trail")
        for before, after in zip(samples, samples[1:]):
            elapsed = (after.timestamp - before.timestamp).total_seconds()
            travelled = after.distance_km - before.distance_km
            if elapsed <= 0 or travelled < 0 or travelled > elapsed * 200 / 3600 + 0.01:
                raise AssertionError(f"{route.train_number}: nonphysical sample progression")
        summaries.append(
            {
                "train_number": route.train_number,
                "samples": len(samples),
                "distance_advanced_km": round(distance, 3),
                "final_delay_minutes": round(samples[-1].delay_minutes, 3),
            }
        )
    events = list(session.scalars(select(Event).where(Event.timestamp >= since)))
    if not events:
        raise AssertionError("No delay events recorded; use --event-every 30 for the smoke run")
    if not any(row["final_delay_minutes"] > 0 for row in summaries):
        raise AssertionError("Delay events did not affect telemetry")
    print(json.dumps({"trains": summaries, "events": len(events)}, indent=2))
    return summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=datetime.fromisoformat, required=True)
    parser.add_argument("--minimum-samples", type=int, default=20)
    args = parser.parse_args()
    if args.since.tzinfo is None:
        parser.error("--since requires an explicit timezone offset")
    with Session(get_engine()) as session:
        verify(session, args.since, args.minimum_samples)
