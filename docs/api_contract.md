# API contract

Local base URL: `http://localhost:8000`. OpenAPI is at `/openapi.json` and the
interactive Swagger UI is at `/docs`. These endpoints are for the local
synthetic demo. Ingestion has shared rate limits and optional Bearer authentication
via INGEST_API_KEY; public reads and WebSockets do not require credentials.
Database/cache ports remain private to the Compose network.

| Method | Path | Purpose | Responses |
| --- | --- | --- | --- |
| GET | `/health` | Process liveness | 200 |
| GET | `/ready` | PostGIS query, seeded route check and Redis ping | 200 / 503 |
| POST | `/ingest/position` | Store validated synthetic telemetry | 201 / 200 / 401 / 404 / 409 / 413 / 422 / 429 / 503 |
| POST | `/ingest/event` | Store a synthetic delay event | 201 / 200 / 401 / 404 / 409 / 413 / 422 / 429 / 503 |
| GET | `/network` | Bundled sourced stations, ordered route stops and timetable offsets | 200 |
| GET | `/trains` | Six seeded trains and latest journey status | 200 / 422 / 503 |
| GET | `/trains/{train_number}/eta` | Upcoming stations, baseline, next-station ML/SHAP and features | 200 / 404 / 422 / 503 |
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

When INGEST_API_KEY is configured, both ingestion endpoints require
`Authorization: Bearer <key>`. Missing or incorrect credentials return HTTP 401
with `WWW-Authenticate: Bearer` before storage access. The key is server-side;
public read endpoints and WebSockets do not require it. An empty key preserves
the local demo behavior. The Render Blueprint configures a generated key.

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

UTC normalization and timetable arithmetic must fit the supported datetime
range; extreme timestamps or delays that would overflow return 422.

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
writes. Read APIs calculate the baseline from committed observations. After a
successful SQL commit, position ingestion atomically invalidates its train's cache,
advances the cache revision and publishes the normalized input JSON to
`<REDIS_KEY_PREFIX>:trains:<train_number>` (default prefix `sih-eta:v1`). It then
fills the cache from the current eligible database observation. Events publish
on the same train channel. Invalid/conflicting requests never publish.

An identical UUID retry also republishes. If Redis fails after SQL commit, the
API returns 503 even though the observation may already be stored. Retrying the
same UUID/body repairs notification/cache delivery without duplicating telemetry.
PostgreSQL and Redis are not one transaction; there is no durable outbox in this
phase. A process crash between commit and notification can lose a pub/sub message;
WebSocket reconciliation and cache expiry recover the current stored state.

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
  still returns the last observation-based prediction with its original `as_of`; it is not refreshed
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
eta               = baseline_eta                     # Phases 3–4
prediction_method = "current_delay_carryover"
model_version     = null
```

The baseline carries the current delay to every remaining stop without recovery,
speed-based extrapolation or extra event penalties. `scheduled_arrival` is the
historical timetable shifted to this simulated journey's start. For example,
the JSON fixture is five minutes late: its NDLS schedule is 18:40 UTC and both
`baseline_eta` and `eta` are 18:45 UTC. The independent `baseline_eta` field stays
available alongside Phase 5 model-backed `eta`, `prediction_method` and
`model_version`; clients will not need a different envelope.

`timing_basis: provided` uses the simulator's immutable origin anchor. For a
legacy journey with no anchor, `inferred_from_first_position` subtracts nominal
schedule progress and reported delay from that journey's earliest sample time.
Between stations, nominal progress is interpolated using source distances;
at a station it uses scheduled arrival (origin departure at the origin).
The inferred anchor is held constant across later samples. A first observation
during dwell is ambiguous, so inferred timing is approximate and explicitly
labeled; it must not be represented as measured departure time.

### Phase 5 additive ML fields

The schema remains `1.0`; existing baseline fields are unchanged. The
[`eta.json`](../backend/tests/examples/eta.json) and corresponding WebSocket
example show the baseline fallback; [`eta_ml.json`](../backend/tests/examples/eta_ml.json)
shows the reviewed model's output for the same observation.

At the response top level and on each predicted station:

- `eta_baseline_minutes`: signed minutes from **as_of** to `baseline_eta`.
- `eta_ml_minutes`: minutes from **as_of** to the ML arrival, or null if unavailable.

Only the **next** station receives ML output. Its `ml_eta` is the model arrival,
`eta` equals `ml_eta`, `prediction_method` is `xgboost_next_station`, and
`model_version` is `synthetic-next-station-v1`. `predicted_delay_minutes` is
relative to `scheduled_arrival`, not the countdown. Later stops retain
`eta=baseline_eta`, `prediction_method=current_delay_carryover` and null ML fields.
Baseline countdowns may be negative when a timetable estimate is already past;
ML arrivals are floored at `as_of`, with the adjustment reported explicitly.

`ml_status` is `ready`, `unavailable` (disabled/missing/incompatible artifact),
`outside_training_domain`, `legacy_timing`, `no_next_station`, or
`prediction_error`. Fallbacks keep baseline service available without claiming a
model output. Existing `active`/`stale` status still governs freshness; countdowns
are never silently rebased to `generated_at`. Inferred legacy anchors are not
eligible for the trained model. No-data/completed responses have null countdowns.

`explanation` on the next station contains exact native TreeSHAP contributions
in minutes for the predicted residual. The additive identity is:

```text
raw_residual_minutes = base_value_minutes + sum(contribution_minutes)
predicted_delay_minutes = current_delay_minutes + raw_residual_minutes
                          + clipping_adjustment_minutes
```

Each contribution has its feature name, observed value (null if missing) and
signed contribution. A positive contribution increases the residual relative to
the model bias, not necessarily relative to the carryover baseline. These are
synthetic model attributions, not causal incident explanations. All contributions
are included. The same fields and computation are used by REST, station boards
and WebSocket messages. Fleet statistics continue to describe observed delays.

Model availability does not alter storage/Redis readiness. Numerical training
range guards and reviewed artifact checks are documented in the
[model card](../ml/README.md), alongside measured synthetic-only accuracy.

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
This avoids interpreting missing/stale data as an on-time train. Phase 4 loads
six latest train states from Redis, recomputing status and delay aggregates at
request time. A warm read makes no PostgreSQL queries. Cache misses use indexed
queries scoped to the missing train, not a full telemetry-table scan. The seeded
fixture supplies the six train numbers; metadata is populated from the database
on a cold fill. Redis is required for this endpoint; failure returns 503 rather
than silently switching every dashboard request to database scans.

Each train state is cached for at most 60 seconds, or until a future-dated
observation becomes eligible, whichever is earlier. An ingest invalidates then
refreshes its train after commit. A Redis revision check prevents a concurrent
older fill from overwriting committed state; retries read the current latest
observation rather than blindly caching the retried payload. Concurrent fills
within one revision also retain the newer as-of time. Stale status is recalculated
from the sample timestamp, not frozen for the cache TTL. Missing/corrupt/evicted
entries rebuild on demand. A commit whose notification is lost can leave an old
cache for up to 60 seconds. Separate deployments must use distinct Redis prefixes.

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

Phase 4 subscribes to the train's Redis channel and waits for the subscription
acknowledgement **before** fetching the initial snapshot. Committed notifications
trigger a fresh baseline/ML calculation off the event loop using a short-lived SQL
session. This works across API processes; no in-process subscription registry
is required. Live acceptance tests require delivery within one second measured
from starting POST to receiving its ETA on an already-open socket.

A changed position, feature, journey or status emits a snapshot; `generated_at`
alone does not cause duplicate updates. Identical ingest retries republish but
do not repeat an unchanged ETA. Bursts may coalesce into the latest state using
a single-slot queue. Client text/binary messages are ignored and cannot trigger
extra queries. Disconnects cancel receivers and release Redis subscriptions.

Pub/sub does not retain messages. A 15-second reconciliation read recovers missed
notifications; a timer also wakes at the 30-second stale boundary. These recovery
reads are separate from the normal notification-driven path and are not the
sub-second delivery mechanism. Redis outages close the socket with an error;
clients reconnect to obtain current state and use history for past observations.
There is no production latency SLA under outage or unbounded load.

Unknown train after connection:

```json
{"type":"error","code":404,"detail":"Train is not in the seeded network"}
```

The server then closes with 1008. A malformed train number is rejected with 1008.
Storage failure:

```json
{"type":"error","code":503,"detail":"Telemetry store unavailable"}
```

Redis failure uses the same close code with:

```json
{"type":"error","code":503,"detail":"Realtime store unavailable"}
```

The server then closes with 1011. HTTP read storage failures use the same
sanitized detail with status 503. A valid unseeded train number returns HTTP 404;
a malformed number returns 422. WebSocket routes are documented here because
OpenAPI does not describe WebSocket transport.

## Ingestion limits and strict JSON

Both ingestion endpoints and all other requests under `/ingest/` share one
Redis-backed fixed-window budget per socket peer: 120 requests per 60 seconds,
starting with that peer's first request. Configure a positive
`INGEST_RATE_LIMIT_PER_MINUTE` to change the budget. Invalid requests and UUID
retries count; GET/WS endpoints do not consume it. Budgets are atomic and shared
across API processes, using expiring keys. IPs are hashed in Redis keys. The
server ignores caller-supplied forwarding headers (`--no-proxy-headers` in
Compose); authentication and a production trusted-proxy policy remain separate.
At a window boundary two budgets can be consumed in quick succession, as with
any fixed-window limiter.

Rate rejection (HTTP 429, with `Retry-After: <remaining seconds>`):

```json
{"detail":"Ingestion rate limit exceeded"}
```

Bodies are bounded to 16,384 bytes before JSON parsing, including chunked bodies.
HTTP 413:

```json
{"detail":"Ingestion body exceeds 16384 bytes"}
```

Malformed JSON, non-finite numbers (`NaN`, `Infinity`, overflow such as `1e9999`),
or excessive JSON nesting return HTTP 422:

```json
{"detail":"Body must be valid JSON with finite numbers"}
```

Normal Pydantic field/domain validation follows after these guards. If Redis is
unavailable during rate checking, the request fails before writing telemetry
(HTTP 503):

```json
{"detail":"Realtime store unavailable"}
```

The same error can occur during post-commit publication; always retain the UUID
and retry the same body. The guard applies the budget before parsing, so malformed
and oversized requests also count. These local demo controls are not authentication.

## Feature definitions

`app.features.compute_features(session, position, stops)` supplies both the
API and the offline training pipeline. Values are calculated **as of the position's
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


## Phase 6 dashboard fields

`GET /network` returns `dataset_version`, `schedule_timezone`, `geometry_kind`,
`stations` (code, name, lat, lon, zone), `routes` (train number/name, total distance
and ordered stops with sequence, station code, arrival/departure seconds and
cumulative distance), and `sources`. It reads the bundled, checksum-tested
historical fixture; it does not download railway data or query telemetry.

Train ETA REST and WebSocket snapshots additionally expose `position` (the full
PositionOut selected by `position_id`, or null) and `active_events` (EventOut
objects, empty if none). Events match the current train/journey and are active
at `as_of`; they use the same observation list as the feature calculation,
ordered by timestamp and ID. Events arriving after the selected position time
are excluded until an eligible observation. These fields let maps, timeline,
explanations and events share a consistent sample rather than racing separate
HTTP reads. Existing ETA fields and fleet-cache semantics are unchanged.

The Next.js app exposes a GET-only `/api/*` proxy for the listed read paths
(network, trains, ETA/history, station arrivals and fleet status). Unknown paths
return 404, unsupported methods 405, and unreachable upstream reads a sanitized
503. It forwards only allowlisted query parameters to a fixed configured server.
WebSockets connect directly to the browser-visible backend URL.
