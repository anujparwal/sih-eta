"""Generate offline journeys with the existing simulator; never write to the live DB."""

import argparse
import gzip
import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.seed import load_dataset
from simulator.engine import Train


def generate(cohorts: int = 18, seed: int = 2026) -> dict:
    dataset = load_dataset()
    stations = {s["code"]: s for s in dataset["stations"]}
    positions, events = [], []
    for cohort in range(cohorts):
        start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=cohort * 4)
        for index, route in enumerate(dataset["routes"]):
            run_seed = seed + cohort * 100 + index
            journey = str(uuid5(NAMESPACE_URL, f"sih-eta-offline-v1/{run_seed}"))
            train = Train(route, stations, start, random.Random(run_seed), journey_id=journey)
            reservations = {}
            previous_station = None
            while True:
                point = train.snapshot()
                if train.elapsed % 120 == 0 or point["last_station"] != previous_station:
                    point["id"] = str(uuid5(NAMESPACE_URL, f"{journey}/p/{train.elapsed}"))
                    positions.append(point)
                previous_station = point["last_station"]
                if train.complete:
                    break
                if train.elapsed > 4 * 86400:
                    raise RuntimeError("Synthetic journey exceeded the four-day cohort spacing")
                for event in train.advance(5, reservations):
                    event["id"] = str(uuid5(NAMESPACE_URL, f"{journey}/e/{event['timestamp']}"))
                    events.append(event)
        print(f"Generated cohort {cohort + 1}/{cohorts}", flush=True)
    return {
        "provenance": {
            "kind": "synthetic",
            "generator": "simulator.engine.Train",
            "seed": seed,
            "cohorts": cohorts,
            "step_seconds": 5,
            "sample_seconds": 120,
            "event_every_seconds": 180,
            "limitations": "Independent journeys; no shared fleet block contention. "
            "Arrival labels have up to five seconds of sampling uncertainty. "
            "Not observed railway performance.",
        },
        "positions": positions,
        "events": events,
        "historical_delays": [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("ml/data/synthetic.json.gz"))
    parser.add_argument("--cohorts", type=int, default=18)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if args.cohorts < 6:
        parser.error("Use at least six cohorts for chronological evaluation")
    data = generate(args.cohorts, args.seed)
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(gzip.compress(raw, mtime=0))
    print(
        json.dumps(
            {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "positions": len(data["positions"]),
                "events": len(data["events"]),
            }
        )
    )


if __name__ == "__main__":
    main()
