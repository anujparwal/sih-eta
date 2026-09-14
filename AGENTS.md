# Contributor guide

## Scope and decisions

This is the SIH 2026 Dynamic ETA Forecast for Coaching Trains monorepo.
Phase 1 is infrastructure scaffolding only. Do not imply that telemetry,
predictions, model evaluation, or the three operational views exist yet.

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
- `simulator/`: future Python telemetry generator (Phase 2).
- `ml/`: future XGBoost training scripts, exported model artifacts, SHAP and evaluation (Phase 5).
- `docs/`: architecture notes and API contract.
- `docker-compose.yml`: local PostgreSQL, Redis, backend and frontend services.

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
docker compose run --rm backend pytest
docker compose run --rm backend ruff check .
docker compose run --rm backend ruff format --check .
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
```

`docker-compose` may be substituted if Compose is installed under that name.
Confirm all four services are healthy and `GET /ready` returns HTTP 200.
There are no ML, simulator or browser-flow test suites in Phase 1; add
meaningful tests when those features are implemented. The frontend currently
has lint, type and production-build checks. See README.md for local commands.
