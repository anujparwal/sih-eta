# Acceptance coverage through Phase 4

Phases 1–4 implement the infrastructure, sourced dataset and simulator, baseline
API/features, and Redis realtime path. All predictions are the current-delay
carryover baseline. ML training/evaluation belongs to Phase 5; passenger,
station-board and control-room interfaces belong to Phase 6. The frontend
identifies Phase 4 and labels those interfaces as planned.

| Phase | Acceptance requirement | Verification |
| --- | --- | --- |
| 1 | Four healthy services; liveness/readiness; reproducible builds | Compose configuration, Docker startup, health tests, frontend lint/typecheck/build |
| 2 | Six sourced routes; preserved PostGIS geometry; repeatable migrations | Dataset/provenance checks, migration round trips/model drift, seed and geometry tests |
| 2 | Ordered, idempotent telemetry; realistic progression | Ingestion validation/retries, deterministic movement/dwell/disruption tests, two-minute HTTP-to-PostGIS smoke |
| 3 | Stable read shapes and honest baseline comparisons | Schema-checked JSON examples, hand-calculated and overnight ETAs, pagination, stale/completed/no-data cases |
| 3 | Reusable features without invented history or future observations | Hand-calculated features; IST day/hour, event expiry, missing evidence, latest-journey congestion and future-data boundaries |
| 4 | Publish after commit and repair failures on UUID retry | Real Redis integration; rejected requests do not publish; post-commit failure retries do not duplicate SQL rows |
| 4 | Sub-second delivery across processes | Two server processes: five timed updates, each under one second; a separate live six-train smoke with a timed update |
| 4 | Fleet aggregation from cached latest state | Warm-read test forbids all SQL; staleness, eviction, corruption, future eligibility and concurrent-fill guards |
| 4 | Shared rate limit and bounded input | Concurrent Redis budget; two workers share limits; spoofed headers, oversized/chunked/malformed/non-finite JSON |
| 4 | Reconnect and cleanup | Initial/reconnected snapshots, duplicate suppression, missed-message reconciliation, stale timer, Redis error closure and subscription cleanup |

The [CI workflow](../.github/workflows/scaffold.yml) runs the combined backend
suite with dedicated PostgreSQL and Redis test databases, Ruff, frontend checks,
four-service health checks, and the two-minute simulation followed by API and
WebSocket verification. The live run requires at least 20 samples spanning at
least 110 seconds per train, recorded events and observable delay. The API smoke
checks all six train baselines, history and station boards, then appends one
synthetic held-position sample to measure delivery to an open WebSocket.

Use the [README commands](../README.md#tests-and-checks) to reproduce the checks.
Omitting TEST_DATABASE_URL or TEST_REDIS_URL skips the corresponding integration
tests; that reduced run is not full acceptance. Test Redis uses DB 15 with unique
prefixes and removes only its own keys. The two-process test cleans up its
subprocesses and recorded journey.

The [API contract](api_contract.md) describes the scope limits: synthetic data
over historical routes and schematic connectors; nondurable Redis pub/sub;
reconciliation/cache expiry after a lost notification; and no model accuracy or
production availability claim. Passing checks establishes the tested behaviors.
