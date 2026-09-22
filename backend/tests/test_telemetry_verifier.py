"""A fresh smoke interval must exclude the default simulator's final sample."""

from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement

from app.models import Event, LivePosition
from app.schemas import EventIn, PositionIn
from app.verify_telemetry import verify
from simulator.engine import Fleet


def test_smoke_cutoff_preserves_subsecond_journey_boundary(db, dataset):
    since = datetime(2026, 1, 1, 0, 0, 0, 800000, tzinfo=UTC)

    def store_positions(fleet):
        for train in fleet.trains:
            position = PositionIn.model_validate(train.snapshot())
            db.add(
                LivePosition(
                    **position.model_dump(),
                    geom=WKTElement(f"POINT({position.lon} {position.lat})", srid=4326),
                )
            )

    # The last default-simulator sample and cutoff fall within the same second.
    store_positions(Fleet(dataset, since - timedelta(milliseconds=500), seed=42))
    smoke = Fleet(dataset, since + timedelta(milliseconds=100), seed=42, event_every=30)
    for tick in range(25):
        for event in smoke.advance(5 if tick else 0):
            db.add(Event(**EventIn.model_validate(event).model_dump()))
        store_positions(smoke)
    db.flush()

    summaries = verify(db, since)
    assert len(summaries) == 6
    assert all(summary["samples"] == 25 for summary in summaries)
    # Reproduce the old shell `date` cutoff: it accidentally includes two journeys.
    with pytest.raises(AssertionError, match="fresh two-minute interval"):
        verify(db, since.replace(microsecond=0))
