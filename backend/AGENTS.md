# Backend

Follow the root guide. Use Python 3.12 and FastAPI. Only `/health` and `/ready`
are implemented in Phase 1; do not add train/ETA endpoints without that scope.
Keep liveness independent of external services; readiness must fail if either
PostGIS or Redis is unavailable. Never expose connection exceptions or secrets.

Run `pytest`, `ruff check .` and `ruff format --check .` from this directory
before considering a backend task done. Alternatively run the corresponding
`docker compose run --rm backend ...` commands at the root. Unit tests do not
require a running database; Compose readiness provides the live service check.

Edit `requirements.in` / `requirements-dev.in`, then regenerate both hashed
lockfiles with `uv pip compile --python-version 3.12 --generate-hashes` as
documented in README.md. Keep runtime pins consistent across both lockfiles.
