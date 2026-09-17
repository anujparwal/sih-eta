# Dynamic Train ETA — SIH 2026

Phase 3 baseline ETA API for coaching trains on Indian routes:
FastAPI, PostgreSQL/PostGIS, Redis, a Next.js/Tailwind shell, and a Python
telemetry simulator. Six **real historical routes** and 63 stations are seeded
from attributed public data. Train positions and incidents are **synthetic**.

The future MVP adds XGBoost with SHAP, measured comparison against a
current-delay carryover baseline, and passenger, station board and control room
views. The current API implements the current-delay carryover baseline and
shared features; ML predictions and operational dashboards remain for later phases.

## Start locally

With Docker Engine/Desktop and Compose v2, from a fresh clone:

```sh
cp .env.example .env
docker compose up --build -d --wait
```

`docker-compose` can be substituted if that is your Compose executable name.
`docker-compose up` also starts the stack in the foreground. The first build
needs internet access to download images/packages. Subsequent runs seed from
the checked-in fixture without downloading railway data.

The backend applies Alembic migrations and seeds the network before serving.
Seeding is idempotent and does not delete telemetry. All four default services
should become healthy. Open [the frontend](http://localhost:3000) or
[API docs](http://localhost:8000/docs). The frontend is still a placeholder;
use the train, ETA, history, station-arrivals and fleet APIs during this phase.

```sh
curl --fail http://localhost:8000/ready
docker compose ps
```

To start continuous simulation as an additional service:

```sh
docker compose --profile simulation up --build -d
```

The simulator emits one sample per train about every five real seconds and
occasionally produces delays. No railway API keys or live feeds are used.

## Two-minute acceptance check

Run this with the four default services healthy and no other simulator running.
It increases disruption frequency to exercise events during a short demo:

```sh
docker compose --profile simulation build simulator
SIMULATION_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
docker compose --profile simulation run --rm -T simulator python -m simulator.simulate --duration 120 --interval 5 --event-every 30
docker compose run --rm -T backend python -m app.verify_telemetry --since "$SIMULATION_START"
docker compose run --rm -T backend python -m app.verify_api
```

The verifier requires at least 20 samples spanning at least 110 seconds per
train, forward movement, plausible speeds, recorded events and observable
delay. It prints per-train counts and distance advanced. GitHub Actions runs
this full check on Docker Engine for each PR, alongside all tests and builds.
The API verifier checks all six baseline comparisons, journey history, station
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

## Baseline API

With simulation running (or within 30 seconds of stopping it):

```sh
curl --fail 'http://localhost:8000/trains?active_only=true'
curl --fail http://localhost:8000/trains/12301/eta
curl --fail 'http://localhost:8000/trains/12301/history?limit=10'
curl --fail http://localhost:8000/stations/NDLS/arrivals
curl --fail http://localhost:8000/control/fleet-status
```

Connect to `ws://localhost:8000/ws/trains/12301` for an initial ETA snapshot and
changed snapshots polled once per second. Every prediction is explicitly a
**current-delay carryover baseline**: shifted timetable arrival + current delay.
The API keeps a separate baseline field for later model comparison. Missing
history stays null; stale telemetry is labeled and excluded from station boards
by default. See the [API contract](docs/api_contract.md) for complete JSON
examples, feature formulas, pagination, error codes and legacy timing limits.

## Tests and checks

The backend image includes tests, simulator tests and Ruff. Create a **dedicated
throwaway test database** once (with the default local credentials):

```sh
docker compose exec -T postgres createdb -U sih_eta sih_eta_test
docker compose run --rm -T -e TEST_DATABASE_URL=postgresql+psycopg://sih_eta:sih_eta_local@postgres:5432/sih_eta_test backend pytest
docker compose run --rm -T backend ruff check .
docker compose run --rm -T backend ruff format --check .
```

If `createdb` reports the database already exists, reuse it. Never point tests
at application data: the migration round-trip test recreates application
tables in the test database. The name must end in `_test`.
`docker compose run --rm backend pytest` without TEST_DATABASE_URL runs unit
and simulator tests, **skipping database integration tests**.

Frontend checks require Node.js 22 and npm:

```sh
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
```

For Python development, from `backend/` with Python 3.12:

```sh
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.txt
.venv/bin/pytest
```

To run the backend outside containers, export POSTGRES_HOST, POSTGRES_PORT,
POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD and REDIS_URL for reachable
services; then run `.venv/bin/alembic upgrade head`, `.venv/bin/python -m app.seed`
and `.venv/bin/uvicorn app.main:app --reload` from `backend/`. The root `.env`
is read by Compose, not automatically by the host Python process. The default
Compose database/cache ports are private. The host simulator needs no packages:
run `python3 simulator/simulate.py --duration 120` from the repository root.

## Layout and data

```text
backend/    Models, migrations, ingestion, baseline ETA/features, REST/WS APIs, tests
simulator/  Real-time synthetic journeys and disruptions
data/       Reproducible six-route historical fixture
scripts/    Checksum-verified source extraction
frontend/   Next.js App Router, TypeScript and Tailwind shell
ml/         Future training, model exports and evaluation
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
with the backend port and rebuild the frontend. The browser URL and server-only
API_INTERNAL_URL are reserved for later UI integration.

```sh
docker compose --profile simulation logs --tail=100
docker compose --profile simulation down
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
See [AGENTS.md](AGENTS.md), [architecture](docs/architecture.md),
[API contract](docs/api_contract.md) and [simulator notes](simulator/README.md).
