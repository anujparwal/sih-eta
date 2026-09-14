# API contract — Phase 1

Local base URL: `http://localhost:8000`. Interactive OpenAPI documentation is
available at `/docs`; machine-readable schema is at `/openapi.json`.

| Method | Path | Purpose | Responses |
| --- | --- | --- | --- |
| GET | `/health` | Process liveness, independent of database/cache | 200 |
| GET | `/ready` | PostGIS query and Redis ping; each bounded to four seconds | 200 or 503 |

Both are bodyless GET requests. `/health` returns:

```json
{"status":"ok"}
```

Ready response (HTTP 200):

```json
{"status":"ok","dependencies":{"postgres":"ok","redis":"ok"}}
```

Example unavailable response (HTTP 503):

```json
{"status":"unavailable","dependencies":{"postgres":"ok","redis":"unavailable"}}
```

Either or both dependencies can report `unavailable`. Failures never include
raw connection errors or credentials. The health routes make no prediction
claims. The train, station, control, ingestion and WebSocket APIs will be
designed in their later phases; no provisional business contract is promised.
