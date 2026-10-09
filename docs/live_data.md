# RailRadar live lookup — Parts 1 and 2

Open `/` or **Find a train** in the navigation; `/live` remains an alias. Enter any
five-digit train number and its optional journey start date (the day it left its origin). Blank
date means today in Asia/Kolkata. Overnight trains may need yesterday's date.
Coverage and accuracy depend on RailRadar. Opening the page or leaving it open
makes no provider requests: submit to fetch, and resubmit to refresh.

## Setup

Set `RAILRADAR_API_KEY=<your-key>` in the root `.env` (ignored by Git).
Rebuild/recreate services with `docker compose up --build -d --wait`.
Compose passes the secret only to the backend. Never use a `NEXT_PUBLIC_` variable.
For a backend launched outside Compose, export the variable in its process
environment; the Python application does not automatically load the root `.env`.

Optional local budgets default to:

```dotenv
RAILRADAR_DAILY_LIMIT=30
RAILRADAR_MONTHLY_LIMIT=900
```

Budgets use UTC calendar days/months and count attempted upstream calls, including
failures. They are shared through Redis, not the provider's remaining balance or
billing reset dates. Other applications, direct requests, different namespaces,
and deleted Redis data are not counted. The current documented free plan has
1,000 requests/month. Adjust limits to the account allowance. This feature does
not purchase a plan or upgrade the account.

## API and safeguards

`GET /live/trains/{train_number}?date=YYYY-MM-DD` accepts any five-digit number;
it does not require a seeded train or write to the synthetic telemetry tables.
The browser calls the same path beneath `/api` through the Next.js proxy.

The normalized response contains `source: "railradar"`, `fetched_at`, `cached`,
`freshness`, `warning`, `cache_seconds: 300`, and `data`. The full schema is in
FastAPI `/docs`. Unknown values remain null; unrecognized provider fields are
removed. Responses for a different train or explicit journey date fail closed.
The upstream host is fixed to HTTPS RailRadar, redirects are rejected, responses
are size limited, and provider error bodies are never forwarded.

- `data.updated_at` is the provider report time, distinct from fetch time.
- `recent` requires `is_live: true` and a report no older than ten minutes.
  Stale, unknown and explicitly non-live responses are labelled. Reports over one
  minute in the future have unknown freshness. Reports age while the page is open.
- `reported_arrival` / `reported_departure` map from upstream `actualArrival` /
  `actualDeparture`. Those fields can contain future estimates, so they are never
  asserted to be observed events or used as model training labels.
- Redis caches account/train/start-date responses for five minutes. A Redis lock
  prevents simultaneous lookups from duplicating upstream requests. Old data is
  retained up to 24 hours and returned with a warning if refresh fails or quota
  runs out. Original timestamps are preserved.
- A one-minute error cooldown prevents repeated failures from using the quota.
  Missing journeys have a separate error cache; other failures cool down the
  account. Redis failure prevents upstream requests rather than bypassing limits.
- 404 means no provider record; 422 means invalid input; 429 means a budget or
  concurrent lookup limit; 503 means key/access, configuration, upstream or Redis
  unavailable. Error messages do not expose raw exceptions or credentials.

This read endpoint is public like existing reads. Anyone able to reach a public
installation can consume its shared budget. This part targets the local student
prototype; shared deployment would need account access control.

## Provider map (Part 2)

Each live lookup now requests `geometry=true&format=geojson&includeCoordinates=true`
from the same provider endpoint. This adds no separate geometry request. The
backend normalizes the provider's wrapped GeoJSON Feature to a validated
`data.geometry` LineString in **longitude, latitude** order. Station coordinates
are normalized to `lat` / `lon`; nested location coordinates are supported.
Fractional route sequence values are preserved for provider-inserted stops.
Invalid optional geometry or coordinates are discarded while status remains
usable. Geometry tagged for a different train is discarded. Map cache entries
are versioned; existing account budgets and error cooldowns are preserved.

- The map draws only supplied geometry. Without it, available station/position
  markers are shown without fabricated connecting lines. If all coordinates are
  absent, a map-unavailable message accompanies the working status/timings.
- A **Provider-reported position** marker requires `isActualPosition: true` and
  valid coordinates. Its accuracy is not independently verified.
- Otherwise, **Last reported station** uses coordinates from the matching route
  stop. Repeated station codes require the matching sequence; ambiguous or
  missing matches produce no location marker. Location coordinates alone are
  never treated as GPS tracking.
- Markers do not animate or extrapolate. Stale, non-live or unverified reports
  show a muted marker and historical-context notice. Report aging preserves the
  user's map view. Use **Fit route** or **Show reported location** to recenter.
- OpenStreetMap supplies base tiles with attribution. If tiles fail, the provider
  geometry and markers remain visible with a notice. Provider labels are rendered
  as text, never executable HTML.

## Scope and next part

Part 1 completes on-demand live train status, route timings, provenance, cache,
limits and error handling. The passenger simulation, station board, control room,
WebSockets, history and ML artifact remain synthetic and separately labelled.
The live page does not present our model's outputs. Its accuracy on real provider
observations has not been evaluated.

Part 2 adds the provider map described above. A later, separate part can collect
and evaluate real observations for the ETA model. A reported station is not continuous GPS.
Never insert arbitrary trains into the synthetic ingestion endpoint.

## Sources and verification

- [RailRadar live status](https://railradar.in/docs/live-train-status)
- [Route geometry formats](https://railradar.in/docs/train-route-geometry)
- [Authentication and free quota](https://railradar.in/docs)

Backend tests mock upstream HTTP and use real Redis for cache, budget, concurrency
and outage behavior. Playwright covers desktop/mobile search, dates, missing
values, stale/non-live status, quota failures, map fallbacks, safe labels, ambiguous
stations, and preservation of the map view as reports age. Automated tests never use the
real key. A separate manual provider call verifies account access and coverage.
