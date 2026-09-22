# Phase 9 — deployment

The supported layout is Render for the API, PostgreSQL/PostGIS, Redis-compatible
Key Value and one continuous simulator worker; Vercel runs the Next.js frontend.
`render.yaml` is configuration for a manual deployment. This phase does not
create cloud accounts, services or a public deployment.

## Start a fresh local demo

Install Docker Engine/Desktop with Compose v2, Git, and internet access for the
first build. From a fresh checkout:

```sh
git clone https://github.com/anujparwal/sih-eta.git
cd sih-eta
cp .env.example .env
docker compose up --build -d --wait
curl --fail http://localhost:8000/ready
curl --fail 'http://localhost:8000/trains?active_only=true'
docker compose ps
```

After this PR is merged, the commands above use the deployment configuration on
`main`. Before merging, check out the PR branch `codex/phase-9-deployment` first.
`docker-compose` is equivalent if that is your Compose executable name.
PostgreSQL, Redis, the API and frontend must be healthy; the fifth service,
`simulator`, must be running. Six trains should become active within the first
few sampling intervals. Open <http://localhost:3000>, `/station/NDLS`, and
`/control`. The API documentation is at <http://localhost:8000/docs>.

The backend's image command, `python -m app.start`, applies Alembic migrations,
seeds the checked-in six-route fixture and then starts Uvicorn. Failed migrations
or seeding stop startup. Repeated startup preserves existing telemetry. The
simulator automatically emits synthetic positions every five seconds and starts
new journeys after a restart. All five services have restart policies. Database
and Redis named volumes survive `docker compose down`.

CI measures the **two-minute startup target after images are built/pulled**, on
empty volumes, including readiness, frontend HTTP and six active trains. First
image downloads and compilation depend on network/hardware and can exceed two
minutes; the cold-clone total is not guaranteed. See the verification results
below for measured local timing.

If a port is occupied, change BACKEND_PORT/FRONTEND_PORT in `.env`; align
NEXT_PUBLIC_API_BASE_URL with the backend's browser-accessible URL and rebuild.
The root `.env` is consumed by Compose, not automatically by host Python/Node.
The default credentials and loopback bindings are for local development.

## Render: API, database, cache and worker

1. Merge the reviewed PR and ensure its GitHub checks pass. In the Render
   dashboard, choose **New → Blueprint**, connect this GitHub repository and
   select `main`, with `render.yaml` at the repository root. Keep automatic
   Blueprint sync disabled so configuration changes also receive manual review.
2. Review the four proposed resources and their cost before creating them. The
   checked-in configuration uses paid API/worker instances, a 256 MB Key Value
   instance and PostgreSQL 15 with a 5 GB disk, all in Singapore. API and worker
   auto-deploy are off. Leave the Docker context at the repository root: the
   backend needs `data/`, `ml/`, and `simulator/` outside `backend/`.
3. Apply the Blueprint when ready to incur those resources. Leave the API's
   Docker command unset so its image startup command runs. Its health check is
   `/ready`, and PORT is 10000. PostgreSQL and Key Value accept private network
   connections only; their generated connection strings are injected into the
   API. The worker resolves the API's private host/port and runs continuously.
4. Wait for the API to become healthy. Logs should show Alembic migrations and
   seeding, followed by the server listening. The migration creates the PostGIS
   extension. Render supports PostGIS on PostgreSQL 13 and later; no TimescaleDB
   extension is required. [PostgreSQL extensions](https://render.com/docs/postgresql-extensions)
5. Confirm the worker is running and keep its instance count at **one**. Its logs
   should show `Starting six simulated journeys`; a permanent ingestion error
   exits visibly. Render workers run continuous processes without an incoming
   HTTP listener. [Background workers](https://render.com/docs/background-workers)
6. Copy the API's actual public HTTPS URL from the dashboard. Check `/health`,
   `/ready`, `/trains?active_only=true` (six trains), and `/trains/12301/eta`
   (`ml_status: ready`, next-station TreeSHAP). Use this URL for Vercel below.

The Blueprint uses generated secrets and service references, not committed
passwords. Its fields and plan identifiers follow the
[Render Blueprint reference](https://render.com/docs/blueprint-spec).
The Dockerfiles supply the API and worker commands; Render supports image CMD
and a worker-specific override. [Docker deployment](https://render.com/docs/docker)

## Vercel: frontend

1. Choose **Add New → Project**, import the same GitHub repository, and select
   `main` as the production branch. Set **Root Directory** to `frontend` and
   framework to **Next.js**. Use `npm ci` for installation and `npm run build`
   for the build; leave Output Directory at the Next.js default. Vercel supports
   selecting a subdirectory for monorepos. [Monorepos](https://vercel.com/docs/monorepos)
2. In project settings, select **Node.js 22.x**, matching the checked-in Docker
   image and CI. `frontend/package.json` also pins `engines.node` to `22.x`,
   because a broad range can override the dashboard selection. [Supported Node.js versions](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions)
3. Add both variables below to the intended Production/Preview environments,
   replacing the example with the actual Render API URL (no trailing slash):

   | Variable | Value | Purpose |
   | --- | --- | --- |
   | `NEXT_PUBLIC_API_BASE_URL` | `https://your-actual-api.onrender.com` | Public browser WebSocket destination; becomes WSS |
   | `API_INTERNAL_URL` | `https://your-actual-api.onrender.com` | Server-side GET proxy destination; Vercel cannot resolve Render's private hostname |

4. Deploy. Verify the passenger page, station board and control room against the
   active six-train API. In browser Network tools, a train WebSocket should
   connect directly to `wss://your-actual-api.onrender.com/ws/trains/12301` and
   receive `eta_update` messages. Render supports WebSockets on public web
   services. [WebSockets](https://render.com/docs/websocket)
5. Redeploy after changing environment variables. NEXT_PUBLIC values are baked
   into the frontend build; changing only a running server variable cannot
   change that bundle. Vercel environment changes apply to new deployments.
   [Environment variables](https://vercel.com/docs/environment-variables)

Keep INGEST_API_KEY out of Vercel and all NEXT_PUBLIC variables. The frontend
only reads; its `/api/*` proxy deliberately rejects ingestion paths. Reads use
same-origin HTTP via that proxy and WebSockets go directly to the API. No browser
cross-origin fetch permission or client-side write credential is needed.

## Configuration reference

| Runtime variable | Configuration |
| --- | --- |
| `DATABASE_URL` | Managed PostgreSQL connection string; accepts `postgres://`, `postgresql://`, or `postgresql+psycopg://`. Preserves escaped credentials and TLS query options. Overrides separate POSTGRES_* settings. Used by migrations, seeding, requests and readiness. |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Local alternative when DATABASE_URL is absent. Compose injects these for the API and database. |
| `PORT` | API listening port, default 8000; Render sets 10000. |
| `REDIS_URL` | Server-only Redis connection string. Compose uses private `redis:6379/0`; Render injects Key Value's internal URL. |
| `REDIS_KEY_PREFIX` | Distinct namespace for each deployment/database sharing Redis. |
| `INGEST_API_KEY` | Optional locally; generated for Render and shared only with the worker. `/ingest/*` requires `Authorization: Bearer <key>` when set; missing/wrong keys receive 401 before storage access. Read/WS endpoints remain public. |
| `INGEST_RATE_LIMIT_PER_MINUTE` | Default 120 per socket peer. Forwarded IP headers are not trusted. Intended for this single-fleet demo. |
| `ETA_MODEL_ENABLED` | `true` loads the reviewed synthetic JSON model; `false` uses the carryover baseline. No cloud training is performed. |
| `API_INTERNAL_HOSTPORT` | Render worker's injected private API host/port; its command prepends `http://`. |
| `API_INTERNAL_URL` | Compose simulator's API URL and Next.js server proxy destination. The Render worker supplies `--api-url` instead. |

## Updating and troubleshooting

Keep one simulator process. Before redeploying the worker, **suspend it and wait
until it has stopped**, then update/resume the desired version. Do not start an
extra worker for a rolling overlap; separate processes create competing journeys.
Before API/database changes, pause simulation, take a database backup, deploy the
API, verify `/ready`, and resume the single worker. Current migrations/seeding are
repeatable; future schema changes still need a reviewed migration/rollback plan.
Do not rerun the Blueprint's initial setup to create duplicate resources.

If readiness fails, inspect API logs and its private connection references;
`/ready` reports PostgreSQL/Redis availability without exposing secrets. A 401
in worker logs means its INGEST_API_KEY differs from the API's. Rotate the key
on both with the worker stopped. A healthy but empty dashboard usually means
the worker stopped; stale telemetry is labeled after 30 seconds. A working HTTP
page with failed live updates usually indicates an incorrect build-time public
API URL or an HTTPS/WSS mismatch. External OSM tiles need internet access.

For the two-minute smoke and live browser checks, stop the default simulator
first, follow [README acceptance commands](../README.md#two-minute-acceptance-check),
then resume it. The test suite clears deployment credentials in its isolated
backend test process; host live tests need the correct INGEST_API_KEY exported.
Never run migration tests against the application database.

The demo continuously accumulates telemetry; monitor disk usage and stop the
worker when not needed. Cloud resources remain billable until managed in their
provider dashboards. Local `docker compose down` preserves volumes; adding `-v`
intentionally deletes local data. Synthetic evaluation scores are not evidence
of real railway accuracy; this phase does not validate cloud availability or load.

## Verification

The CI workflow runs on every push and pull request: frontend lint/types/build,
76 desktop/mobile browser checks, a fresh five-service Docker startup, the full
backend/ML suite with required PostGIS/Redis, Ruff, two-minute telemetry and API/WS
verification, and the real-stack browser check. It provisions no cloud resources.
The Render configuration is also checked locally against Render's published JSON
schema; an actual provider deployment remains a manual acceptance step.

Local verification on 22 September 2026 (Compose against rootless Podman):

- Fresh volumes and prebuilt images: **31.12 seconds** to four healthy services
  plus the running worker. The first samples for all six trains were stored
  about 21 seconds after container creation. Cold image build time is excluded.
- **174 backend/ML tests passed with zero skips**, including the real service
  tests inside the backend image; Ruff lint and formatting passed.
- Frontend lint, types and production build passed; **76 deterministic browser
  tests** and **one browser test against the new container stack** passed.
- Authenticated two-minute smoke: **150 positions, seven events**, six active
  trains, model/SHAP and station checks passed; HTTP-to-WebSocket delivery
  measured **78.89 ms**. Both unauthenticated ingestion paths returned 401.
- The Blueprint matched `https://render.com/schema/render.yaml.json`. No actual
  Render or Vercel deployment was performed.
