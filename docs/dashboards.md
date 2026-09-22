# RailScope dashboards — Phases 6–7

Run the stack and simulator using the root README, then open port 3000.
The app labels all telemetry as simulated. Historical timetable coordinates and
schematic connectors come from `/network`; no station or train data is invented
by the frontend. This is a local demonstration, not a live railway service.

## Passenger · `/`

Search the six seeded train names/numbers and choose a service. The URL preserves
selection as `?train=12301`, including links from station arrivals. Leaflet shows
that route's station connectors and current observed position. A WebSocket
snapshot updates the position, next ETA, timeline and SHAP explanation together.
The next-station card displays the ML ETA beside the crossed-out carryover
baseline only when a model prediction exists. Later stations keep the baseline.
Elapsed stops are labeled reached without inventing actual arrival timestamps.
Schedules and arrivals include IST calendar dates for overnight journeys.

## Station board · `/station/[code]`

Select any of the 63 seeded stations. The high-contrast board polls arrivals
every 10 seconds and displays receipt age separately from each train's observation
status. Columns show scheduled and expected IST time/date, prediction method,
platform placeholder and predicted delay. Platforms remain `—` because the
source has no operational assignments. Empty boards explain why no fresh train
is approaching. Rows link back to the corresponding passenger view.

## Control room · `/control`

Fleet state polls every five seconds while six train WebSockets update positions
and predictions. Summary counts include only fresh active trains. The table can
be sorted by train, observed delay or ML delay trend, and filtered by status.
The map colors observed delays; stale/completed trains are neutral. Select a map
marker or View button to open a keyboard-accessible modal with the full route,
current journey events, SHAP explanation and recorded positions from the history
API. History loads chronologically in pages of 100; reopen detail to refresh it.

ML trend is the change in predicted delay, not a countdown or a change in current
observed delay. It compares successive predictions only within the same journey,
next station and model version. A new comparison is required after any of those
change. A trend is displayed only for the matching observation and a fresh train.

## Shared states and transport

- Green: no delay. Amber: greater than zero but less than 15 minutes. Red:
  15 minutes or more. Thresholds use unrounded values; labels truncate to one
  decimal so 14.99 minutes stays amber and reads 14.9, not 15. Positive delays
  below one minute read `<1 min late`.
- Passenger/board arrival badges describe estimated delay at that station;
  fleet badges and counts describe observed current delay.
- Active observations become stale after 30 seconds even if every connection
  fails. Missing data never becomes a zero delay or a fabricated position.
  Model fallback keeps the independent carryover estimate and labels its method.
- All three views have responsive loading skeletons, including route navigation.
  Loading, no telemetry, an unknown train and failed reads have distinct messages.
  A route error boundary provides a retry if an unexpected render fails.
- WebSockets reconnect with bounded exponential backoff (1–10 seconds). Backoff
  resets and the feed shows live only after a valid train snapshot arrives, not
  merely when the socket opens. Connections without an initial snapshot close
  after eight seconds and retry. HTTP
  snapshots also poll every 10 seconds. Older generated snapshots cannot replace
  newer ones. Cleanup aborts outstanding requests and disposes timers/sockets.
  Request failures retain the last known data with a visible error;
  station/network/fleet/history reads offer retry controls. Individual prediction
  failures are also visible in the control room. Missing fleet responses show
  unavailable counts rather than zero. Map markers retain their DOM elements
  during clock and telemetry updates, preserving keyboard focus.
- Browser HTTP uses the same-origin, GET-only Next.js allowlisted proxy.
  `API_INTERNAL_URL` is server-only; `NEXT_PUBLIC_API_BASE_URL` is fixed at build
  time and must point to a browser-reachable backend for WebSockets. Without a
  public URL override, local development uses the page hostname on port 8000.
- OpenStreetMap tiles are fetched on demand with visible attribution. No bulk
  tile fetching/caching is included. If tiles fail, routes and positions remain
  visible. CI replaces only tile responses to avoid loading the public service.

## Verification

`npm run lint`, `npm run typecheck`, `npm run build`, and `npm run test:e2e`
run from `frontend/`. Install Chromium first with
`npx playwright install --with-deps chromium`. The deterministic suite checks
all three views on desktop and a mobile Chromium device profile, including live
updates, freshness, recovery, sorting/filtering, history and overnight dates.
Phase 7 adds service outages, delay boundaries, rejected WebSocket backoff,
console-error assertions and 320/650/768/1024 px layout checks. Details and
verification results are in the [review report](phase7_review.md).

`npm run test:live` runs against the healthy local stack (default simulator stopped) immediately
after the two-minute simulator smoke and API verifier, with no simulator still
posting. It checks a real ingestion-to-browser WebSocket update and corresponding
station/control displays. `UI_BASE_URL` and `LIVE_API_URL` override local URLs.
The GitHub workflow runs both suites; backend tests cover the sourced network
response and sample-consistent position/event fields. No model training is run
as part of these checks.
