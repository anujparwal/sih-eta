# Backend

Follow the root guide. Use Python 3.12, FastAPI, SQLAlchemy 2, Alembic and PostGIS.
Phase 4 exposes health/ingestion, train ETA/history, station arrivals, Redis-cached
fleet status and Redis-driven WebSocket snapshots. Preserve the
versioned response shapes and independent baseline fields when adding the model.
Never substitute invented zeros for unknown history or observed station timing.

Run `pytest`, `ruff check .` and `ruff format --check .` before finishing.
For full coverage, set TEST_DATABASE_URL to a disposable database ending in
`_test`; integration tests include migration downgrade/upgrade and model drift
checks. Redis tests also require TEST_REDIS_URL using database 15. Tests isolate
keys with a per-test UUID prefix and never flush shared Redis data. Missing service
URLs explicitly skip service tests. See the root README for exact
container commands. Unit and simulator tests do not need PostgreSQL.

Use explicit Alembic revisions; never create application tables during an HTTP
request. Migrations must preserve the PostGIS extension. Seed from the bundled
fixture, keep existing telemetry, and do not fabricate historical delays.
Keep source coordinates and POINT geometries consistent. Route LineStrings are
schematic station connectors; timetable distance is a separate measurement.

Keep liveness independent of dependencies. Readiness requires PostGIS, seeded
routes and Redis. Ingest retries must be idempotent: identical UUID/body returns
200; changed content with the same UUID returns 409. Return sanitized 503 errors
when storage is unavailable. Serialize writes per train when validating sample
order. Never expose credentials or raw database exceptions.

Edit requirements.in / requirements-dev.in and regenerate both hashed lockfiles
with `uv pip compile --python-version 3.12 --generate-hashes`. Verify the same
runtime pins occur in both. The Docker build context is now the repository root.


Publish only after SQL commit; an identical UUID retry must repair delivery after
a Redis failure. Do not cache a retried payload blindly: select the latest eligible
row. Preserve cache generation/as-of guards and future-observation boundaries.
Warm fleet reads must not query SQL. Ingest limits must be atomic across workers,
include invalid requests and bound raw bodies before parsing. Do not trust caller
forwarding headers in the local server. Test actual Redis and two API processes;
normal ingest-to-open-WebSocket delivery must remain under one second.
