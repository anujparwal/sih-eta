# Phase 7 — cross-cutting bug pass

Reviewed 21 September 2026 against the merged Phase 6 implementation. The pass
covered passenger search → station arrivals → control room → train detail,
backend read/error handling, realtime recovery, delay thresholds and narrow
layouts. `frontend/tests/hardening.spec.ts` records the regressions alongside
Phase 6's existing browser tests. All fixes below are included in Phase 7.

## Findings and resolutions

| Finding / reproduction | Resolution and verification |
| --- | --- |
| Open `/?train=99999`: route loading continued indefinitely and departure copy implied a known train. | Resolve the selection against the seeded network before subscribing. Show “Train not found” and allow a valid train selection. Covered on desktop/mobile. |
| Return 503 from `/network`: passenger/control maps continued to show loading after the request failed. | End loading with a route/map-unavailable message and retry. All three views have network failure/recovery checks. |
| Fail the initial train ETA read and live feed: the passenger displayed “Waiting for departure” and “Not started” despite having no observation. | Distinguish unavailable estimates/positions from a successful no-data response. Do not display a journey timeline before a snapshot arrives. Detail also distinguishes loading from failure. |
| Reject one prediction feed while the control fleet request succeeds: its failure was hidden. | Surface affected train numbers while retaining available observed positions. Test restoration through HTTP fallback. |
| Fail the initial fleet request: coverage counters implied zero stale/completed/awaiting trains without evidence. | Show unavailable values until the fleet response exists. Test retry and restored rows/counts. |
| Accept then immediately reject a WebSocket (the backend's Redis-unavailable behavior): every open reset the retry delay and temporarily claimed live delivery. | Mark live/reset backoff only after a valid snapshot. Retry at 1/2/4/8/10 seconds; close connections without an initial snapshot after eight seconds. Test rejected connections and a combined HTTP/socket outage, retained/stale data and automatic recovery. |
| Navigating away while a WebSocket is connecting can produce a browser “closed before connection established” error. | Cancel subscriptions and handlers; close a pending socket when it opens. The complete client navigation flow asserts no page or console errors. |
| Every clock tick rebuilt all Leaflet markers, removing focused DOM nodes and tooltips. | Retain markers by train number; update position, label and color in place. Remove only absent trains. Regression checks that marker elements survive clock and telemetry updates. |
| A delay of 14.99 minutes was amber but its rounded label read 15 minutes, contradicting the red threshold. | Keep raw thresholds and truncate labels to one decimal; positive delays below one minute read `<1 min late`. Test 0, 14.99 and 15 minutes. |
| Initial view loading used generic bars alongside operational content. | Dedicated responsive passenger, station and control skeletons at route and initial client-load boundaries. Tests hold requests pending and verify skeletons without departure claims. Add a shared retry boundary for unexpected render failures. |
| The mobile detail panel used `100vw`; with a classic scrollbar, it extended 15 px past the left edge at 320 px. Standard overlay-scrollbar tests missed it. | Use the containing viewport's available width (`100%`). Reproduced in the in-app browser and a desktop Chromium regression that reserves a scrollbar gutter. Test detail/page bounds at 320, 650, 768 and 1024 px. |

## Additional review coverage

- Station request timeout, station 503 after a good response, retained arrivals
  becoming stale without fresh telemetry, and recovery all remain explicit.
- Initial history failure/retry and pagination failure/retry preserve observations.
- Empty/no-data/completed trains, model fallback, overnight IST dates, fleet
  sorting/filtering and journey-scoped prediction trends retain Phase 6 coverage.
- Backend review found no additional defect requiring a backend change. The full
  integration suite verifies sanitized database failures across read endpoints,
  Redis failures, WebSocket 404/503 closure, cross-process publication, shared
  limits, migration round trips, ingestion, simulator, feature parity and model
  fallback/SHAP behavior.
- The actual running browser walkthrough searched for 12621, opened its next
  station BZA, entered control, and inspected its timeline/events/history. The
  healthy flow produced no browser console errors. Deliberately failed network
  requests may produce browser network diagnostics; those are separate from the
  healthy-flow assertion and have visible application recovery states.

## Validation

- All 115 backend tests passed against dedicated PostGIS and Redis test services;
  none skipped. Ruff lint and formatting checks passed for all Python sources.
- Frontend lint, strict type checking and production build passed.
- All 70 deterministic browser tests passed (35 each on desktop/mobile),
  including the scrollbar regression reproduced during manual inspection.
- The two-minute real-stack simulation wrote 150 positions (25 per train) and
  seven events. All six trains advanced; telemetry and API verifiers passed.
- Baseline comparisons, model/SHAP output, station boards and 13 WebSocket
  connections passed the API verifier. Local HTTP-to-WebSocket delivery measured
  65.84 ms in this run; this is a smoke measurement, not a latency guarantee.
- The real-stack Playwright test passed ingestion → Redis/API → all three browser
  views with the production frontend. No mocked train data is used in that test.

PostGIS and Redis ran in rootless Podman containers locally, with the application
and test processes on the host. GitHub CI runs the repository's Compose workflow.
This phase does not retrain or change the synthetic model and makes no new claim
about real-world forecast accuracy or production readiness.
