# Contributor guide

## Scope and decisions

This is the SIH 2026 Dynamic ETA Forecast for Coaching Trains monorepo.
Phase 6 adds passenger, station and control dashboards over the evaluated
synthetic XGBoost/TreeSHAP and Redis-backed APIs. Phase 7 hardens loading,
error states, reconnect behavior and map updates; see docs/phase7_review.md.
Phase 8 extends automated coverage; docs/testing.md maps requirements to tests.
Phase 9 makes the simulator a default service and adds Render/Vercel deployment
configuration; docs/deployment.md describes the manual cloud setup.
Phase 10 adds docs/README.md as the submission overview and a pitch-ready
architecture summary. Keep measured metrics tied to ml/results/metrics.json and
clearly distinguish synthetic evidence from real railway performance.
See ml/README.md for model
provenance and evaluation limits, and docs/dashboards.md for frontend behavior.

The upgraded `sih_plan.md` takes precedence over the older Astra plan where
they differ: PostgreSQL **with PostGIS**, exactly **six simulated coaching
trains** on real Indian routes, **XGBoost with SHAP**, and a **current-delay
carryover baseline**. TimescaleDB is not part of the selected stack.

MVP target: one model evaluated against that baseline, with passenger,
station board, and control room views in one Next.js app served by one API.
Telemetry is synthetic; station/route data must have cited real sources.
Never claim the model beats the baseline until measured evaluation proves it.

## Layout and stack

- `backend/`: Python 3.12, FastAPI; PostgreSQL 15 + PostGIS 3.3 and Redis 7.4.
- `frontend/`: Node.js 22, Next.js App Router, TypeScript, React, Tailwind CSS 4.
- `simulator/`: Python telemetry generator with synthetic delay events.
- `data/`: checksum-pinned historical network fixture; provenance in `docs/data_sources.md`.
- `ml/`: XGBoost training scripts, reviewed JSON artifact, SHAP and synthetic evaluation.
- `docs/`: architecture notes and API contract.
- `docker-compose.yml`: local PostgreSQL, Redis, backend, frontend and continuous simulator services.

## Conventions

Use Python snake_case with type annotations, four-space indentation and Ruff.
Use strict TypeScript, PascalCase React components and two-space indentation.
Keep Next.js route files under `frontend/app/`. Keep API logic under
`backend/app/`; tests go in `backend/tests/`. Prefer small, focused changes
and descriptive Conventional Commits (for example `feat: scaffold services`).
Keep dependency lockfiles in sync with their inputs. Do not commit `.env`,
credentials, dependency caches, generated builds or undocumented datasets.
Avoid training ML models inside a multi-file implementation task; perform
training separately and integrate a reviewed artifact when Phase 5 is in scope.

## Verification

From the repository root, with Docker Engine and Compose v2:

```sh
cp .env.example .env # only if .env does not already exist
docker compose up --build -d --wait
docker compose exec -T postgres createdb -U sih_eta sih_eta_test # once, for default local credentials
docker compose run --rm -e INGEST_API_KEY= -e TEST_DATABASE_URL=postgresql+psycopg://sih_eta:sih_eta_local@postgres:5432/sih_eta_test -e TEST_REDIS_URL=redis://redis:6379/15 backend pytest --require-services
docker compose run --rm backend ruff check .
docker compose run --rm backend ruff format --check .
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
```

`docker-compose` may be substituted if Compose is installed under that name.
Confirm four services are healthy, the simulator is running, all six trains
become active and `GET /ready` returns HTTP 200. Stop the default simulator
before the bounded two-minute smoke and real browser checks; resume it afterward.
Integration tests require a dedicated database whose name ends in `_test`; the
migration round-trip test recreates its application tables. Never use the running
application database for tests. Redis tests require TEST_REDIS_URL on database 15
and isolate/clean only their own UUID-prefixed keys. Missing service test URLs
explicitly skip the corresponding integration tests. The suite also launches two
temporary API processes to verify cross-process delivery and shared limits.
Simulator tests are included in the backend suite. Run the two-minute smoke check
in README.md before declaring telemetry work complete. The same smoke also validates the read APIs and real WebSocket delivery.
ML artifact, feature parity, leakage, SHAP and fallback tests are included.
Default pytest collection includes ml/tests in both checkout and container layouts.
Use --require-services for acceptance and CI; service-free partial runs may skip integrations.
Run frontend Playwright desktop/mobile flows and the real-stack browser smoke
after the API verifier; see README.md. Use Ruff with `--config backend/pyproject.toml` for root Python scripts.

Keep the PostGIS choice: indexed PostgreSQL time-series tables replace the older
plan’s TimescaleDB hypertable. Use timezone-aware UTC telemetry and unwrapped IST
schedule offsets. Preserve historical source names/codes and label connector
geometry, block occupancy and telemetry as synthetic approximations. Never seed
invented historical delay averages. Migration and seed commands must be repeatable.
