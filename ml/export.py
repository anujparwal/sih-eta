"""Export a consistent database snapshot for offline training; no model fitting or DB mutation."""

import argparse
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Event, HistoricalDelay, LivePosition
from app.read_schemas import PositionOut
from app.schemas import EventIn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(connection) as session:
            positions = [
                PositionOut.model_validate(p).model_dump(mode="json")
                for p in session.scalars(select(LivePosition).order_by(LivePosition.timestamp))
            ]
            events = [
                EventIn.model_validate({k: getattr(e, k) for k in EventIn.model_fields}).model_dump(
                    mode="json"
                )
                for e in session.scalars(select(Event))
            ]
            history = [
                {c.name: getattr(h, c.name) for c in HistoricalDelay.__table__.columns}
                for h in session.scalars(select(HistoricalDelay))
            ]
    data = {
        "provenance": {
            "kind": "synthetic",
            "generator": "database telemetry export",
            "exported_at": datetime.now(UTC).isoformat(),
            "historical_delays": "Exported for audit; excluded from model inputs",
        },
        "positions": positions,
        "events": events,
        "historical_delays": history,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, sort_keys=True).encode()
    args.output.write_bytes(gzip.compress(raw, mtime=0) if args.output.suffix == ".gz" else raw)


if __name__ == "__main__":
    main()
