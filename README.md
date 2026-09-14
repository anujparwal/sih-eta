# Dynamic Train ETA — SIH 2026

Phase 1 scaffold for coaching train ETA forecasting on Indian routes.
FastAPI + PostgreSQL/PostGIS + Redis + Next.js/Tailwind, in one monorepo.

The planned MVP is six simulated coaching trains, an XGBoost ETA model with
SHAP explanations evaluated against a current-delay carryover baseline, and
passenger, station board and control room views served by one API. **This
phase contains infrastructure only**: no route data, telemetry, predictions
or operational dashboards are implemented yet.

## Start locally

Install Docker Engine or Docker Desktop with Compose v2. From a fresh clone:

```sh
cp .env.example .env
docker compose up --build -d --wait
docker compose ps
```

If your Compose command is named `docker-compose`, the equivalent is:

```sh
docker-compose up --build -d --wait
```

`docker-compose up` also runs the stack in the foreground. The first build
downloads images and dependencies and can take several minutes. All four
services should become healthy. `.env.example` contains local development
defaults; never use its password for a public deployment.

| Service | Address / purpose |
| --- | --- |
| Frontend | http://localhost:3000 — static scaffold page |
| Backend docs | http://localhost:8000/docs |
| Liveness | http://localhost:8000/health |
| Readiness | http://localhost:8000/ready — PostGIS and Redis checks |
| PostgreSQL / Redis | Compose network only; no published host ports |

```sh
curl --fail http://localhost:8000/ready
docker compose logs --tail=100
docker compose down
```

`down` preserves named volumes. `docker compose down -v` **deletes local
database and Redis data**; use it only when intentionally resetting the demo.
Changing database credentials in `.env` does not update an existing database
volume. Use the original credentials or deliberately reset disposable data.
If a port is busy, change `BACKEND_PORT` or `FRONTEND_PORT`; update
`NEXT_PUBLIC_API_BASE_URL` alongside the backend port and rebuild the frontend.
The public API URL is a build argument reserved for later browser API calls;
`API_INTERNAL_URL=http://backend:8000` is reserved for server-side calls.

## Layout

```text
backend/    FastAPI, infrastructure endpoints and pytest checks
frontend/   Next.js App Router, TypeScript and Tailwind shell
ml/         Future training, model artifacts and evaluation results
simulator/  Future Python synthetic telemetry generator
docs/       Architecture and API contract
```

## Checks

The `Phase 1 scaffold` GitHub Actions workflow runs on pull requests. It checks
frontend lint/types/build, starts all four services on Docker Engine with
health checks, and runs backend tests and style checks inside the container.

Backend tests and style checks use the same image as the running service:

```sh
docker compose run --rm backend pytest
docker compose run --rm backend ruff check .
docker compose run --rm backend ruff format --check .
```

Frontend checks need Node.js 22 and npm on the host:

```sh
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
```

There are no train/ML/simulator/browser-flow tests yet because those features
are not implemented. Backend tests cover liveness, dependency failure behavior
and the published infrastructure routes. The container startup check exercises
real PostGIS and Redis connections.

For backend-only development, from `backend/` with Python 3.12:

```sh
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/uvicorn app.main:app --reload
```

Liveness works without backing services; readiness correctly returns 503
until reachable PostgreSQL/PostGIS and Redis are configured. The host backend
does not automatically read the root `.env`. Supply `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and
`REDIS_URL` in its environment for your own accessible services. The default
Compose database/cache are intentionally not published to the host.

For frontend development, run `npm run dev` in `frontend/` after `npm ci`.
Stop the Compose frontend first if using the same port.

Python lockfiles include transitive dependency pins and hashes. To update
them, install `uv`, edit the `.in` files, then run from `backend/`:

```sh
uv pip compile requirements.in --python-version 3.12 --generate-hashes -o requirements.txt
uv pip compile requirements-dev.in --python-version 3.12 --generate-hashes -o requirements-dev.txt
```

Keep runtime dependency versions consistent across the two lockfiles.
Frontend versions are pinned in `package.json` and `package-lock.json`.

See [AGENTS.md](AGENTS.md), [architecture](docs/architecture.md) and the
[Phase 1 API contract](docs/api_contract.md) before starting the next phase.
