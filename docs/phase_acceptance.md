# Acceptance coverage through Phase 5

Phases 1–5 implement infrastructure, sourced routes, the simulator, baseline
APIs, Redis realtime delivery, and evaluated next-station ML with SHAP.
Passenger, station-board and control-room interfaces remain for Phase 6.
The frontend identifies Phase 5 and labels those interfaces as planned.

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

| 5 | Shared features and chronological evaluation without label leakage | Database/offline feature parity, observed station targets, disjoint complete journeys, purged split boundaries |
| 5 | Meaningful carryover comparison | 66 training / 18 validation / 24 test journeys; MAE 33.941 → 5.759 min, RMSE 45.098 → 8.013 min; all six train groups improve |
| 5 | Reviewed artifact and exact SHAP | JSON/network checksums, feature/objective validation, SHAP additive identity and published model card |
| 5 | REST, station boards and WS agree | Same next-station prediction path; independent baseline; downstream, legacy and unavailable/out-of-domain fallbacks |
| 5 | Reproducible training and history-job stub | Deterministic seeded telemetry generator, hashed data manifest, versioned inputs; idempotent observed-arrival aggregation with dry-run default |

The [CI workflow](../.github/workflows/scaffold.yml) runs the combined backend
suite with dedicated PostgreSQL and Redis test databases, Ruff, frontend checks,
four-service health checks, and the two-minute simulation followed by API and
WebSocket verification. The live run requires at least 20 samples spanning at
least 110 seconds per train, recorded events and observable delay. The API smoke
checks all six train baselines, ML/SHAP, history and station boards, then appends one
synthetic held-position sample to measure delivery to an open WebSocket.

Use the [README commands](../README.md#tests-and-checks) to reproduce the checks.
Omitting TEST_DATABASE_URL or TEST_REDIS_URL skips the corresponding integration
tests; that reduced run is not full acceptance. Test Redis uses DB 15 with unique
prefixes and removes only its own keys. The two-process test cleans up its
subprocesses and recorded journey.

The [API contract](api_contract.md) describes the scope limits: synthetic data
over historical routes and schematic connectors; nondurable Redis pub/sub;
reconciliation/cache expiry after a lost notification; and no real-world railway accuracy or
production availability claim. Passing checks establishes the tested behaviors.
