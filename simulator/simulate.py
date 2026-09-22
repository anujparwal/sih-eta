"""Publish six synthetic train journeys over HTTP using a real-time simulation clock."""

import argparse
import json
import logging
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__:
    from .engine import Fleet
else:
    from engine import Fleet

LOGGER = logging.getLogger("simulator")


def post(base_url: str, path: str, payload: dict, attempts: int = 5) -> None:
    """Retry transient errors with exactly the same ID/body, so acknowledgements can be lost."""
    body = json.dumps(payload, allow_nan=False).encode()
    headers = {"Content-Type": "application/json"}
    if key := os.getenv("INGEST_API_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    for attempt in range(attempts):
        try:
            request = Request(
                base_url.rstrip("/") + path,
                data=body,
                headers=headers,
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                if response.status not in (200, 201):
                    raise RuntimeError(f"Unexpected ingestion status: {response.status}")
                return
        except HTTPError as error:
            if error.code < 500 and error.code != 429:
                raise RuntimeError(
                    f"Ingestion rejected payload ({error.code}): {error.read().decode()}"
                ) from error
        except (URLError, TimeoutError, ConnectionError):
            pass
        if attempt + 1 < attempts:
            LOGGER.warning(
                "Ingestion unavailable; retrying saved sample (%s/%s)", attempt + 1, attempts
            )
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"Ingestion unavailable after {attempts} attempts")


def positive(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("API_INTERNAL_URL", "http://localhost:8000"))
    parser.add_argument("--interval", type=positive, default=5)
    parser.add_argument("--duration", type=positive, help="Stop after this many real seconds")
    parser.add_argument(
        "--event-every",
        type=positive,
        default=180,
        help="Mean seconds between disruptions, with a 20 second minimum",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "rail_network.json",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dataset = json.loads(args.dataset.read_text())
    started_at = datetime.now(UTC)
    start = time.monotonic()
    fleet = Fleet(dataset, started_at, args.seed, args.event_every)
    elapsed, positions, event_count = 0.0, 0, 0
    LOGGER.info("Starting six simulated journeys; dataset=%s", dataset["dataset_version"])
    try:
        while True:
            now = time.monotonic() - start
            if args.duration is not None:
                now = min(now, args.duration)
            events = fleet.advance(now - elapsed)
            for event in events:
                post(args.api_url, "/ingest/event", event)
                event_count += 1
            for train in fleet.trains:
                post(args.api_url, "/ingest/position", train.snapshot())
                positions += 1
            elapsed = now
            if args.duration is not None and elapsed >= args.duration:
                break
            remaining = args.interval
            if args.duration is not None:
                remaining = min(remaining, args.duration - elapsed)
            time.sleep(max(0, start + elapsed + remaining - time.monotonic()))
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user")
    LOGGER.info(
        "Finished: %s positions, %s events, %.1f simulated seconds", positions, event_count, elapsed
    )


if __name__ == "__main__":
    main()
