# Dynamic Train ETA — SIH 2026

RailScope provides dashboards and an ETA API for coaching trains on Indian routes:
FastAPI, PostgreSQL/PostGIS, Redis, a Next.js/Tailwind app, and a Python
telemetry simulator. Six **real historical routes** and 63 stations are seeded
from attributed public data. Train positions and incidents are **synthetic**.

Phase 5 adds a reviewed XGBoost model with exact TreeSHAP explanations for the
**next station**, alongside the independent current-delay carryover baseline.
On 24 held-out synthetic journeys, MAE is **5.76 minutes versus 33.94** for the
baseline (83.0% lower); RMSE is **8.01 versus 45.10 minutes**. These numbers
measure this simulator, **not real railway accuracy**. See the [model card and
reproduction steps](ml/README.md) and [evaluation](ml/results/comparison.md).
Phase 6 provides three responsive **RailScope** dashboards:

- [Passenger](http://localhost:3000): search six trains, watch live positions on
  Leaflet/OpenStreetMap, and compare next-station ML and carryover estimates.
- [Station board](http://localhost:3000/station/NDLS): choose any of 63 stations;
  high-contrast arrivals refresh every 10 seconds, with IST dates and update age.
- [Control room](http://localhost:3000/control): monitor six trains, filter and
  sort delays/trends, and open a journey's timeline, recorded history and events.

All views label simulated telemetry, stale/missing signals and model fallbacks.
Platforms are unavailable placeholders. Maps use schematic station connectors.
Phase 7 adds loading skeletons, explicit failure/retry states, reliable WebSocket
reconnection and stable map markers. See the [bug-pass report](docs/phase7_review.md).

For the submission overview, model results, limitations and a short demo sequence,
start with [docs/README.md](docs/README.md).

## Start locally

Install Git and Docker Engine/Desktop with Compose v2, start Docker, and use a
POSIX shell (Linux/macOS or WSL on Windows). No host Python/Node installation or
model training is needed for the container demo. From a new terminal:

```sh
git clone https://github.com/anujparwal/sih-eta.git
cd sih-eta
cp .env.example .env
docker compose up --build -d --wait
```

On an existing checkout, run from the repository root and keep your existing
`.env`; copy the example only if that file is absent. Ports 3000 and 8000 must be
free (see [configuration](#configuration-and-cleanup) for alternate ports).

`docker-compose` can be substituted if that is your Compose executable name.
`docker-compose up` also starts the stack in the foreground. The first build
needs internet access to download images/packages. Subsequent runs seed from
the checked-in fixture without downloading railway data.

The backend applies Alembic migrations and seeds the network before serving.
Seeding is idempotent and does not delete telemetry. All five services start
automatically: four report healthy and the continuous simulator reports running.
Open [the frontend](http://localhost:3000) or [API docs](http://localhost:8000/docs).
The dashboards populate with six active trains without another command.

```sh
curl --fail http://localhost:8000/ready
docker compose ps
```

The simulator emits one sample per train about every five real seconds and
occasionally produces delays. No railway API keys or live feeds are used.
Use `docker compose stop simulator` to pause it and `docker compose start simulator`
to resume with new journeys. For Render and Vercel setup, see the
[deployment guide](docs/deployment.md). It includes environment variables,
startup timing, single-worker updates and verification; no cloud services have
been provisioned by this repository change.

## Two-minute acceptance check

Run this with PostgreSQL, Redis, the backend and frontend healthy. The command
below stops the default simulator first; stop any host simulator too.
It increases disruption frequency to exercise events during a short demo:

```sh
docker compose stop simulator
SIMULATION_START="$(docker compose exec -T backend python -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')"
docker compose run --rm -T --no-deps simulator python -m simulator.simulate --duration 120 --interval 5 --event-every 30
docker compose run --rm -T backend python -m app.verify_telemetry --since "$SIMULATION_START"
docker compose run --rm -T backend python -m app.verify_api
```

The cutoff is captured inside the running backend with sub-second precision so
a final sample from the stopped simulator cannot leak into the new run.
The verifier requires at least 20 samples spanning at least 110 seconds per
train, forward movement, plausible speeds, recorded events and observable
delay. It prints per-train counts and distance advanced. GitHub Actions runs
this full check on Docker Engine for every push and PR, alongside all tests and builds.
The API verifier checks all six baseline/ML comparisons and SHAP payloads, journey history, station
boards, 12 initial/reconnected WebSocket snapshots and one HTTP-to-WebSocket
update. It appends one synthetic held-position sample to verify update delivery.
Run it immediately after simulation stops, before the 30-second freshness window
expires, and with no other simulator active.

Inspect stored data directly:

```sh
docker compose exec postgres psql -U sih_eta -d sih_eta -c 'SELECT train_number, count(*), min(timestamp), max(timestamp) FROM live_positions GROUP BY train_number ORDER BY train_number;'
docker compose exec postgres psql -U sih_eta -d sih_eta -c 'SELECT train_number, event_type, severity, duration_seconds FROM events ORDER BY timestamp DESC LIMIT 10;'
```

These examples use the default local credentials; adapt them if `.env` differs.

## ETA API

With simulation running (or within 30 seconds of stopping it):

```sh
curl --fail 'http://localhost:8000/trains?active_only=true'
curl --fail http://localhost:8000/trains/12301/eta
curl --fail 'http://localhost:8000/trains/12301/history?limit=10'
curl --fail http://localhost:8000/stations/NDLS/arrivals
curl --fail http://localhost:8000/control/fleet-status
```

Connect to `ws://localhost:8000/ws/trains/12301` for an initial ETA snapshot and
changed snapshots driven by Redis pub/sub. The live smoke requires delivery
within one second; a 15-second reconciliation check recovers missed notifications. The next station has both baseline and ML countdowns, a model version and SHAP
contributions. Downstream stations retain the carryover baseline. Missing,
incompatible or out-of-domain models fall back to the baseline with an explicit
`ml_status`. All countdowns are relative to `as_of`, not response time. Missing
history stays null; stale telemetry is labeled and excluded from station boards
by default. See the [API contract](docs/api_contract.md) for complete JSON
examples, feature formulas, pagination, error codes and legacy timing limits.

## Realtime behavior

Committed position and event updates publish to train-specific Redis channels.
A warmed fleet-status request aggregates six Redis-cached train states without
querying PostgreSQL. Ingestion updates the affected cache; missing/expired state
is rebuilt with indexed per-train queries. Status still ages from active to stale
without new telemetry. History and baseline ETA contracts are unchanged.

All `/ingest/*` requests share a Redis budget of **120 requests per 60 seconds
per socket peer**, configurable with INGEST_RATE_LIMIT_PER_MINUTE. The normal
six-train simulator fits this budget. Rejections return 429 with Retry-After;
bodies above 16 KiB return 413, and invalid/non-finite JSON returns 422. Forwarded
IP headers are not trusted; the supplied server disables proxy headers. This is
a demo limit. Set INGEST_API_KEY to require a matching Bearer token on ingestion;
the Render configuration generates and shares this secret with its worker. Read
endpoints remain public. See the deployment guide for the hosting configuration.

Redis failure returns a sanitized 503. A failure after SQL commit can leave the
observation stored, so **retry the same UUID and body**; the retry republishes
without another row. Pub/sub is not a durable queue: reconnecting gets the latest
snapshot, periodic reconciliation recovers missed notifications, and history
remains in PostgreSQL. Warm caches expire within 60 seconds even if a process
fails between commit and invalidation. Use a distinct REDIS_KEY_PREFIX for each
deployment/database sharing the same Redis database. The complete semantics are
in the [API contract](docs/api_contract.md).

## Tests and checks

Phase 8 coverage and the complete acceptance commands are documented in
[the test guide](docs/testing.md). Acceptance uses `--require-services` so missing
PostGIS/Redis configuration cannot silently skip integration coverage.

The backend image includes tests, simulator tests and Ruff. Create a **dedicated
throwaway test database** once (with the default local credentials):

```sh
docker compose exec -T postgres createdb -U sih_eta sih_eta_test
docker compose run --rm -T -e INGEST_API_KEY= -e TEST_DATABASE_URL=postgresql+psycopg://sih_eta:sih_eta_local@postgres:5432/sih_eta_test -e TEST_REDIS_URL=redis://redis:6379/15 backend pytest --require-services
docker compose run --rm -T backend ruff check .
docker compose run --rm -T backend ruff format --check .
```

If `createdb` reports the database already exists, reuse it. Never point tests
at application data: the migration round-trip test recreates application
tables in the test database. The name must end in `_test`.
`docker compose run --rm backend pytest` without TEST_DATABASE_URL and
TEST_REDIS_URL runs unit and simulator tests, **skipping service integration tests**.
Redis integration tests require database 15 and use a unique key prefix per test;
they delete only their own keys. The suite starts two temporary API processes
to verify cross-process notification delivery and a shared ingestion budget.

Frontend checks require Node.js 22 and npm:

```sh
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
npx playwright install --with-deps chromium
npm run test:e2e
```

The desktop/mobile suite uses deterministic test fixtures and mocked OSM tiles.
For the real API/Redis/model browser check, run `npm run test:live` from
`frontend/` immediately after the two-minute smoke and API verifier, with no
other simulator running. It adds one synthetic held-position sample and checks
its WebSocket update, station arrival and journey history in the browser.
`UI_BASE_URL` and `LIVE_API_URL` can override the default localhost ports.
If ingestion authentication is enabled, export INGEST_API_KEY for the host
simulator and live browser test. Never put it in a NEXT_PUBLIC_ variable.
After the smoke and browser check, run `docker compose start simulator` to resume.

For Python development, from `backend/` with Python 3.12:

```sh
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.txt
.venv/bin/pytest
```

To run the backend outside containers, export POSTGRES_HOST, POSTGRES_PORT,
POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD and REDIS_URL for reachable
services; then run `.venv/bin/alembic upgrade head`, `.venv/bin/python -m app.seed`
and `.venv/bin/uvicorn app.main:app --reload --no-proxy-headers` from `backend/`. The root `.env`
is read by Compose, not automatically by the host Python process. The default
Compose database/cache ports are private. The host simulator needs no packages:
run `python3 simulator/simulate.py --duration 120` from the repository root.

## Layout and data

```text
backend/    Models, migrations, ingestion, baseline ETA/features, REST/WS APIs, tests
simulator/  Real-time synthetic journeys and disruptions
data/       Reproducible six-route historical fixture
scripts/    Checksum-verified source extraction
frontend/   Next.js passenger, station and control dashboards
ml/         Offline training, reviewed JSON model, SHAP and measured evaluation
docs/       Architecture, complete API contract and data provenance
```

See [data sources](docs/data_sources.md) for pinned URLs, checksums, attribution,
route selection and historical-data limitations. Route geometries join station
coordinates schematically; they are **not surveyed railway tracks**. Directional
5 km occupancy blocks demonstrate a simplified mechanism, not real signal
locations or an operational rail safety model. Schedule distances remain the
source timetable's kilometre values; they are not replaced with straight-line
geometry lengths. The historical_delays table starts empty.

## Configuration and cleanup

The `.env.example` defaults are for local development. Backend/frontend ports
bind to loopback; PostgreSQL and Redis are not published. If a port is busy,
change BACKEND_PORT or FRONTEND_PORT. Keep NEXT_PUBLIC_API_BASE_URL aligned
with the backend port and rebuild the frontend. Browser HTTP reads use the Next.js `/api/*` proxy and server-only
API_INTERNAL_URL (Compose default `http://backend:8000`). The proxy allows only
known read endpoints and does not expose ingestion. WebSockets connect directly
to NEXT_PUBLIC_API_BASE_URL; use HTTPS there for WSS on an HTTPS frontend.
OSM tiles require internet access and retain visible attribution. If tiles fail,
the schematic routes and position markers still work; no offline tile download
or prefetching is performed. See [dashboard behavior](docs/dashboards.md).

```sh
docker compose logs --tail=100
docker compose down
```

`down` preserves data volumes. `down -v` **deletes local database/cache data**;
use it only to intentionally reset the demo. Changing credentials in `.env`
does not change an existing database volume's credentials. A new simulator
process creates new journey IDs, preserving old trails separately. Run one
simulator process at a time for the six-train demo.

Python dependency inputs and hashed locks are in `backend/`. After changing
the `.in` files, regenerate from `backend/` with `uv`:

```sh
uv pip compile requirements.in --python-version 3.12 --generate-hashes -o requirements.txt
uv pip compile requirements-dev.in --python-version 3.12 --generate-hashes -o requirements-dev.txt
```

Keep runtime pins identical in both locks; commit frontend package-lock.json.
See [phase acceptance](docs/phase_acceptance.md), [AGENTS.md](AGENTS.md),
[architecture](docs/architecture.md),
[API contract](docs/api_contract.md) and [simulator notes](simulator/README.md).
