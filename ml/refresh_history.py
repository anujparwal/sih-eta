"""Manual scheduled-job stub: derive station history from observed synthetic arrivals."""

import argparse
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database import get_engine
from app.features import IST
from app.models import HistoricalDelay, LivePosition, RouteStop
from app.seed import load_dataset
from ml.dataset import observed_arrivals


def aggregates(positions: list[LivePosition]) -> list[dict]:
    journeys = defaultdict(list)
    routes = {
        r["train_number"]: [RouteStop(**s) for s in r["stops"]] for r in load_dataset()["routes"]
    }
    for position in positions:
        journeys[(position.train_number, position.journey_id)].append(position)
    buckets = defaultdict(list)
    for (number, _), points in journeys.items():
        for station, (observed_at, delay) in observed_arrivals(
            sorted(points, key=lambda p: p.timestamp), routes[number]
        ).items():
            local = observed_at.astimezone(IST)
            buckets[(number, station, local.weekday(), local.hour)].append(delay)
    return [
        dict(
            train_number=number,
            station_code=station,
            day_of_week=day,
            hour_of_day=hour,
            avg_delay_minutes=sum(values) / len(values),
            sample_count=len(values),
        )
        for (number, station, day, hour), values in sorted(buckets.items())
    ]


def refresh(session: Session, before: datetime, apply: bool = False) -> list[dict]:
    if before.tzinfo is None:
        raise ValueError("History cutoff must be timezone-aware")
    rows = aggregates(
        list(session.scalars(select(LivePosition).where(LivePosition.timestamp < before)))
    )
    if apply:
        for row in rows:
            statement = insert(HistoricalDelay).values(**row)
            session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_historical_delay_hour",
                    set_={
                        "avg_delay_minutes": statement.excluded.avg_delay_minutes,
                        "sample_count": statement.excluded.sample_count,
                    },
                )
            )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Upsert derived averages; default is dry run"
    )
    args = parser.parse_args()
    # for production: retrain nightly
    # Wire this command to an external scheduler with a single-run lock and monitoring.
    # Version historical snapshots before adding history as a model feature; never
    # automatically deploy a retrained model without fresh chronological evaluation.
    with Session(get_engine()) as session, session.begin():
        rows = refresh(session, datetime.now(UTC), apply=args.apply)
    print(f"{'Updated' if args.apply else 'Would update'} {len(rows)} observed-arrival buckets")


if __name__ == "__main__":
    main()
