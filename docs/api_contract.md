# API contract — Phase 3

Local base URL: `http://localhost:8000`. OpenAPI is at `/openapi.json` and the
interactive Swagger UI is at `/docs`. These endpoints are for the local
synthetic demo. Authentication/rate limiting remain for later phases. Database/cache ports remain private to the Compose network.

| Method | Path | Purpose | Responses |
| --- | --- | --- | --- |
| GET | `/health` | Process liveness | 200 |
| GET | `/ready` | PostGIS query, seeded route check and Redis ping | 200 / 503 |
| POST | `/ingest/position` | Store validated synthetic telemetry | 201 / 200 / 404 / 409 / 422 / 503 |
| POST | `/ingest/event` | Store a synthetic delay event | 201 / 200 / 404 / 409 / 422 / 503 |
| GET | `/trains` | Six seeded trains and latest journey status | 200 / 422 / 503 |
| GET | `/trains/{train_number}/eta` | Upcoming stations, baseline and features | 200 / 404 / 422 / 503 |
| GET | `/trains/{train_number}/history` | Paginated observed journey positions | 200 / 404 / 422 / 503 |
| GET | `/stations/{code}/arrivals` | Upcoming arrivals ordered by ETA | 200 / 404 / 422 / 503 |
| GET | `/control/fleet-status` | Fleet status and active-train delay summary | 200 / 503 |
| WS | `/ws/trains/{train_number}` | Initial ETA snapshot, then changed snapshots | See transport contract below |

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
  "journey_started_at": "2026-09-16T00:00:00+00:00",
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
Phase 3 adds optional `journey_started_at`: the aware timestamp corresponding
to the simulated origin departure. The simulator always supplies it. It cannot
follow the sample timestamp and must remain unchanged (including null vs non-null)
throughout a train/journey; a conflicting start returns 409. Legacy clients may
omit it. Existing records remain null after migration. This is the simulation
anchor, not the archived timetable's wall-clock departure on today's date.

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
writes. Read APIs calculate the baseline from committed observations. Redis publishing
remains for Phase 4.

## Read semantics and examples

GET requests have **no JSON request body**. Use URL query parameters. All JSON
examples linked below are complete responses generated against the seeded
network with a synthetic fixture; tests validate them against the response
models. They are illustrative observations, not current railway information.

All reads use the latest observation at or before server UTC time, selecting
one journey per train. Historical journeys never blend with the selected
journey. `generated_at` is the response time; `as_of` is the latest position
used for prediction. Future-dated telemetry is excluded until its timestamp.
Ties between different journeys use descending sample UUID for deterministic
selection; normal operation runs only one simulator.

Status definitions:

- `no_data`: no observation at or before response time. Null position/timing/
  features and empty predictions are intentional; seeded schedules alone do not
  assert that a train is running.
- `active`: unfinished journey with its latest sample at most 30 seconds old.
- `stale`: unfinished journey with a sample older than 30 seconds. An ETA request
  still returns the last baseline with its original `as_of`; it is not refreshed
  or extrapolated as if telemetry were live.
- `completed`: latest observation has `next_station: null`, regardless of age.
  No upcoming stations remain. A subsequent journey replaces this status.

### Train list

```sh
curl --fail 'http://localhost:8000/trains?active_only=true'
```

Response: [trains.json](../backend/tests/examples/trains.json).
Without `active_only=true`, all six seeded trains appear in train-number order,
including no-data, stale and completed trains. `latest_position` is the full
normalized position (or null). Malformed boolean query values return 422.

### ETA and baseline comparison

```sh
curl --fail 'http://localhost:8000/trains/12301/eta'
```

Response: [eta.json](../backend/tests/examples/eta.json).
`stations` includes stops **after** `last_station` in schedule order. A station
where the train is dwelling has already been reached and is excluded. There is
no arbitrary forecast horizon; every remaining stop, including the terminal,
is returned. All outputs use aware UTC timestamps, including overnight arrivals.

For every upcoming station:

```text
scheduled_arrival = journey_started_at
                    + (station.arrival_seconds - origin.departure_seconds)
baseline_eta      = scheduled_arrival + current_delay_minutes
eta               = baseline_eta                     # Phase 3
prediction_method = "current_delay_carryover"
model_version     = null
```

The baseline carries the current delay to every remaining stop without recovery,
speed-based extrapolation or extra event penalties. `scheduled_arrival` is the
historical timetable shifted to this simulated journey's start. For example,
the JSON fixture is five minutes late: its NDLS schedule is 18:40 UTC and both
`baseline_eta` and `eta` are 18:45 UTC. The independent `baseline_eta` field stays
available when Phase 5 supplies a model-backed `eta`, `prediction_method` and
`model_version`; clients will not need a different envelope.

`timing_basis: provided` uses the simulator's immutable origin anchor. For a
legacy journey with no anchor, `inferred_from_first_position` subtracts nominal
schedule progress and reported delay from that journey's earliest sample time.
Between stations, nominal progress is interpolated using source distances;
at a station it uses scheduled arrival (origin departure at the origin).
The inferred anchor is held constant across later samples. A first observation
during dwell is ambiguous, so inferred timing is approximate and explicitly
labeled; it must not be represented as measured departure time.

### Journey history

```sh
curl --fail 'http://localhost:8000/trains/12301/history?limit=1'
```

Response: [history.json](../backend/tests/examples/history.json).
The default journey is the latest one, and the default page size is 100.
`limit` accepts 1–1000. Records are ordered by timestamp ascending. To read an
older run, add its UUID as `journey_id`; a journey not recorded for that train
returns 404. For subsequent pages, retain that `journey_id` and pass the returned
`next_after` as the exclusive `after` cursor. `next_after: null` means there is
no further page at response time. URL-encode offsets containing `+` or use `Z`.
`after` must carry a timezone. Retaining `journey_id` avoids switching runs if
the simulator restarts during pagination. History contains observed positions,
not manufactured station arrival records.

### Station arrivals

```sh
curl --fail 'http://localhost:8000/stations/NDLS/arrivals'
```

Response: [arrivals.json](../backend/tests/examples/arrivals.json).
Only active trains that have not yet reached the station appear, ordered by ETA
then train number. `include_stale=true` opts into stale forecasts, clearly labeled
with their timestamp and status. No-data/completed trains never appear. A known
station with no upcoming trains returns an empty list; unknown station codes
return 404. Codes are case-sensitive historical codes from the fixture.

### Control-room fleet summary

```sh
curl --fail 'http://localhost:8000/control/fleet-status'
```

Response: [fleet_status.json](../backend/tests/examples/fleet_status.json).
The response includes all six train summaries and mutually exclusive counts
for active/stale/completed/no-data. Delay metrics use **active trains only**:
`delayed_active_trains` counts delay greater than zero, and mean/max include
on-time active trains. With no active trains, both mean and maximum are null.
This avoids interpreting missing/stale data as an on-time train. Redis caching
is not part of Phase 3.

### WebSocket ETA updates

Connect to `ws://localhost:8000/ws/trains/12301`; no request body or subscription
message is needed. Example browser client:

```js
const socket = new WebSocket("ws://localhost:8000/ws/trains/12301");
socket.onmessage = ({ data }) => console.log(JSON.parse(data));
// When finished: socket.close();
```

Initial and changed response example:
[websocket.json](../backend/tests/examples/websocket.json).
Each `{"type":"eta_update","data":{...}}` contains the same complete ETA
shape as GET, including `schema_version: "1.0"`. The initial snapshot is sent
immediately, even for `no_data`. Reconnecting gets the current snapshot, not a
replay log. Use history for past positions.

Phase 3 polls the database once per second per connection using short-lived
sessions off the event loop. A changed position, feature, journey or status
emits a new snapshot; `generated_at` alone does not cause duplicate updates.
A train becoming stale also emits an update. Intermediate observations between
polls can be coalesced. This is not a guaranteed sub-second stream; Redis
pub/sub, caching and rate limiting remain Phase 4. Client text/binary messages
are ignored and do not accelerate polling. Disconnects release the receiver
and no database connection is held while waiting.

Unknown train after connection:

```json
{"type":"error","code":404,"detail":"Train is not in the seeded network"}
```

The server then closes with 1008. A malformed train number is rejected with 1008.
Storage failure:

```json
{"type":"error","code":503,"detail":"Telemetry store unavailable"}
```

The server then closes with 1011. HTTP read storage failures use the same
sanitized detail with status 503. A valid unseeded train number returns HTTP 404;
a malformed number returns 422. WebSocket routes are documented here because
OpenAPI does not describe WebSocket transport.

## Feature definitions

`app.features.compute_features(session, position, stops)` supplies both the
API and future model integration. Values are calculated **as of the position's
timestamp**, excluding later observations/events. Default nearby radius is 5 km.

| Field | Definition |
| --- | --- |
| `minutes_since_last_station` | Minutes since the earliest same-journey observation at the last station (within 0.01 source km). Origin uses the provided departure anchor. A station observation approximates arrival to the telemetry interval; if no arrival was observed, null. |
| `distance_remaining_next_station_km` | Next stop's source distance minus the current source distance, lower-bounded at zero; zero at terminal. |
| `current_delay_minutes` | Current telemetry delay, unchanged. |
| `historical_avg_delay_minutes` | Exact train/next-station/current-IST-weekday/current-IST-hour bucket; null if unavailable. Monday = 0. Lookup uses observation time, not projected arrival time. |
| `historical_sample_count` | Bucket sample count, zero when no matching history is available. |
| `active_event_count` | Number of same-train/same-journey events with start <= as_of < start + duration. Zero when the journey is complete. |
| `active_event_severity_sum` / `active_event_max_severity` | Sum and maximum of active severity values (1–3); both zero when none are active. |
| `congestion_index` | Count of other trains whose latest observation is within the previous ten minutes (inclusive), on the same unordered adjacent-station pair and within 5 km great-circle distance. Both directions count. |

Simulator events affect their train/journey's remaining travel, hence
`event_scope: train_journey`. They are not geographically fixed incidents or
alerts affecting unrelated trains. Congestion chooses each other train's latest
observation **before** applying section/age filters, preventing old positions or
restarted journeys from being counted twice. It uses schematic coordinates;
shared track hidden by different stopping patterns is outside this approximation.

`missing` names unavailable features explicitly; absent history/arrival evidence
is never silently replaced with a measured zero. Historical hour buckets allow
0–23. Migration gives pre-existing daily aggregates hour -1 (unknown), retains
their values, and excludes them from hourly lookup. History starts empty. Any
future history import must use attributed past measurements; Phase 3 does not
collect, train on, or seed invented delay averages. Downgrade refuses to discard
hourly records: export and remove those records before downgrading to Phase 2.
