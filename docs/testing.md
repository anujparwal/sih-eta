# Phase 8 — automated test coverage

The suite extends the tests built during Phases 1–7. It exercises the selected
PostGIS/Redis stack and the reviewed XGBoost **JSON** model. The older build
plan's `eta_model.pkl` request is satisfied by loading the artifact actually
shipped in `ml/models/eta_model.json`; no pickle or retraining is introduced.

## Coverage map

| Area | Evidence |
| --- | --- |
| Feature arithmetic | `backend/tests/test_features.py`: hand-calculated values; IST midnight, week/year/leap-day boundaries; observed zero versus missing data; terminal behavior; nonnegative remaining distance; microsecond event windows; inclusive radius and dateline/antipodal distance. |
| Database feature selection | `test_read_api.py` and `test_ml.py`: observed arrival time, hourly history, latest journey before congestion filtering, future-data exclusion and offline/serving parity. |
| Every documented HTTP endpoint | `test_endpoint_contract.py`: ten parameterized successful requests with real PostGIS/Redis, response validation and sample identity; documented endpoint inventory agrees with OpenAPI and the WebSocket router. Also rejects malformed query parameters. |
| Ingestion and errors | `test_ingest.py`, `test_read_api.py`, `test_realtime.py`, `test_health.py`: idempotency, ordering, geometry, validation, rate/body limits, sanitized outages, readiness and fallback behavior. |
| Real WebSocket push | `test_realtime_workers.py`: two independent API processes; ingest on one, subscribe on the other. Five position updates and a separate incident update arrive within one second. The incident updates features/events without another position. Reconnect retains the snapshot; cleanup releases subscriptions. |
| WebSocket edge cases | `test_websocket.py`: initial snapshot, duplicate suppression, stale transition, missed notification reconciliation, malformed train, sanitized SQL/Redis errors and close codes. |
| Shipped model | `ml/tests/test_artifact.py`: load reviewed bytes, predict a finite positive delay for a known input, reload consistently, reject corrupted bytes. Existing `test_ml.py` covers SHAP, domain fallback, metadata rejection, split leakage, metrics and feature parity. |
| Three browser flows | `frontend/tests/ui.spec.ts` and `hardening.spec.ts`: passenger search/selection and saved links, station selection/arrivals, control sorting/filtering/detail/history. Desktop/mobile, loading/outage/recovery, stale states, delay thresholds, responsive bounds, keyboard actions and focus restoration. |
| Real browser integration | `frontend/tests/live.spec.ts`: actual passenger search, ingestion-to-browser update, matching station ETA and control detail against the running API/model. Console and page errors fail the test. Only public map tiles are replaced. |
| CI configuration | `test_test_configuration.py`: the full-suite flag refuses missing service URLs before collection instead of reporting a partial pass with skipped integration tests. |

## Run the acceptance suite

From the repository root, with Docker Engine and Compose v2, follow README.md to
start all four services. Create the dedicated test database once:

```sh
docker compose exec -T postgres createdb -U sih_eta sih_eta_test
docker compose run --rm -T \
  -e TEST_DATABASE_URL=postgresql+psycopg://sih_eta:sih_eta_local@postgres:5432/sih_eta_test \
  -e TEST_REDIS_URL=redis://redis:6379/15 \
  backend pytest --require-services
docker compose run --rm -T backend ruff check .
docker compose run --rm -T backend ruff format --check .
cd frontend
npm ci
npx playwright install --with-deps chromium
npm run lint
npm run typecheck
npm run build
npm run test:e2e
```

Adjust credentials for a customized environment. The test database name must end
in `_test`; Redis tests require database 15 and use UUID-prefixed keys. Never
point these tests at the application database. Integration fixtures roll back
transactions; the two-process test explicitly cleans its own committed positions
and events. Migration tests recreate application tables in the dedicated test DB.

`--require-services` is used by CI and should be used for acceptance. Without it,
ordinary `pytest` still permits service-free development and reports skipped
integration cases when their URLs are missing. That partial run is not acceptance.
Unreachable services fail rather than skip.

For host execution, set the same two URLs to your test services, then run
`.venv/bin/pytest --require-services` from `backend/`. Pytest's configured search
paths include `../ml/tests` in the checkout and `ml/tests` in the backend image;
the same model tests are collected in either layout. To run just the model smoke
from the repository root:

```sh
backend/.venv/bin/pytest -c backend/pyproject.toml ml/tests
```

The real-browser test is separate: run the README's two-minute simulator smoke
and API verifier, stop any other simulator, then immediately run
`npm run test:live` from `frontend/` while observations remain fresh. The existing
GitHub workflow runs this sequence after its container and deterministic tests.

## Findings from the added tests

The keyboard test reproduced lost focus after closing control-room train detail.
React removes the dialog before its passive cleanup, preventing native dialog
focus restoration. The detail now preserves and restores the connected opener
explicitly; both desktop and mobile keyboard tests enforce it.

The expanded run also exposed two test synchronization issues: a train selector
could match the Leaflet marker as well as the picker, and advancing virtual time
before the network fixture finished could time out an unrelated request. Tests
now scope picker controls and wait for that response before driving the intended
timeout. No application assertion was removed to get a green result.

These tests verify the local synthetic demo. Chromium mobile emulation is not a
real-device or cross-browser certification, and model smoke checks do not measure
real railway accuracy. CI loads the reviewed model; it never trains one.

## Phase 8 local results — 22 September 2026

- Backend/ML: **151 passed, zero skipped**, including real PostGIS/Redis and the
  two-process position/event push test. Ruff lint and formatting passed.
- Frontend: **76 passed** across desktop and mobile Chromium; lint, strict
  type checking and the production build passed.
- These totals extend Phase 7's 115 backend and 70 deterministic browser tests.
  The real-stack browser test remains a separate acceptance check.
