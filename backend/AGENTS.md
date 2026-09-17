# Backend

Follow the root guide. Use Python 3.12, FastAPI, SQLAlchemy 2, Alembic and PostGIS.
Phase 3 exposes health/ingestion, train ETA/history, station arrivals, fleet status
and polling WebSocket snapshots. Redis pub/sub remains Phase 4. Preserve the
versioned response shapes and independent baseline fields when adding the model.
Never substitute invented zeros for unknown history or observed station timing.

Run `pytest`, `ruff check .` and `ruff format --check .` before finishing.
For full coverage, set TEST_DATABASE_URL to a disposable database ending in
`_test`; integration tests include migration downgrade/upgrade and model drift
checks. Without that variable, database tests skip. See the root README for exact
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
