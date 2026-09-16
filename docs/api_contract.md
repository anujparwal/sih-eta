# API contract — Phase 2

Local base URL: `http://localhost:8000`. OpenAPI is at `/openapi.json` and the
interactive Swagger UI is at `/docs`. These endpoints are for the local
synthetic demo. Authentication/rate limiting and business read APIs arrive in
later phases. Database/cache ports remain private to the Compose network.

| Method | Path | Purpose | Responses |
| --- | --- | --- | --- |
| GET | `/health` | Process liveness | 200 |
| GET | `/ready` | PostGIS query, seeded route check and Redis ping | 200 / 503 |
| POST | `/ingest/position` | Store validated synthetic telemetry | 201 / 200 / 404 / 409 / 422 / 503 |
| POST | `/ingest/event` | Store a synthetic delay event | 201 / 200 / 404 / 409 / 422 / 503 |

Liveness returns `{"status":"ok"}`. Readiness returns
`{"status":"ok","dependencies":{"postgres":"ok","redis":"ok"}}` when
ready; unavailable dependencies become `"unavailable"` and the top-level status
becomes `"unavailable"` with HTTP 503. Dependency checks are bounded to four
seconds each and execute concurrently. No connection errors or secrets leak.

## Position ingestion

Content-Type: application/json. Example `POST /ingest/position` on train 12301,
30 simulated seconds after leaving historical HWH:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "journey_id": "22222222-2222-4222-8222-222222222222",
  "train_number": "12301",
  "timestamp": "2026-09-16T00:00:30+00:00",
  "lat": 22.586411599999998,
  "lon": 88.3397613,
  "distance_km": 0.375,
  "delay_minutes": 0.0,
  "current_speed_kmh": 45.0,
  "last_station": "HWH",
  "next_station": "DKAE",
  "source": "simulator"
}
```

`id` identifies the sample; `journey_id` groups one simulated train run. Both
must be UUIDs. `train_number` must be a seeded five-digit string. Timestamps
must include a timezone; they are normalized to UTC in PostgreSQL timestamptz.
Distance and delay are nonnegative; speed is 0–200 km/h; coordinates are finite
and within valid latitude/longitude bounds. `source` defaults to `simulator`
and accepts no other value. Unknown fields are rejected.

`last_station` is the last reached stop, and `next_station` is the following
stop in this route. During dwell, last_station is the current station. At the
terminal, next_station is null and speed must be zero. Distance must lie between
the named stops. Coordinates must match the schematic connector fraction within
0.001 degrees per axis (roughly 100 metres, latitude-dependent).

Within a train/journey, timestamps must increase and distance cannot decrease.
Distance jumps faster than the 200 km/h ceiling (plus 0.01 km tolerance) are
rejected. A restarted train uses a new journey_id. A UUID retry must retain all
other values; do not regenerate timestamps or coordinates while retrying.

## Event ingestion

Example `POST /ingest/event`:

```json
{
  "journey_id": "22222222-2222-4222-8222-222222222222",
  "train_number": "12301",
  "timestamp": "2026-09-16T00:00:30+00:00",
  "source": "simulator",
  "id": "33333333-3333-4333-8333-333333333333",
  "event_type": "unscheduled_stop",
  "severity": 2,
  "duration_seconds": 120,
  "description": "Synthetic unscheduled stop; not a reported railway incident."
}
```

Event types: speed_restriction, unscheduled_stop, congestion, weather. Severity
is 1–3, duration_seconds is 1–3600 and description is 1–500 characters. The
active interval starts at timestamp and ends after duration_seconds. Shared
UUID/train/timestamp/source rules are identical to positions. Events may arrive
before the first position; journey_id links observations without requiring a
separate journey-creation endpoint. All event descriptions should state that
they are synthetic. The built-in simulator emits durations of 60–180 seconds.

## Response and retry semantics

New record, HTTP 201:

```json
{"id":"11111111-1111-4111-8111-111111111111","status":"created"}
```

Retry of identical normalized content, HTTP 200:

```json
{"id":"11111111-1111-4111-8111-111111111111","status":"duplicate"}
```

- 404: train is not seeded.
- 409: UUID reused with changed content, duplicate train/journey timestamp, or
  out-of-order/backwards sample. Existing rows are never overwritten.
- 422: malformed input, nonadjacent station pair, invalid position or excessive
  distance jump. FastAPI field errors use its normal `detail` list; domain errors
  use `{"detail":"reason"}`.
- 503: storage is unavailable; response is
  `{"detail":"Telemetry store unavailable"}`. Retry using the same UUID/body.

Requests serialize per train to make ordering checks safe against concurrent
writes. Ingestion does not publish to Redis, compute ETA or expose read APIs.
Those contracts remain for Phases 3–4.
