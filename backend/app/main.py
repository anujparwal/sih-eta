"""Synthetic telemetry, baseline ETA contracts and dependency health."""

import asyncio
import os

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.exc import SQLAlchemyError

from app.ingest import router as ingest_router
from app.read_api import router as read_router

app = FastAPI(title="Dynamic Train ETA", version="0.3.0")
app.include_router(ingest_router)
app.include_router(read_router)


@app.exception_handler(SQLAlchemyError)
async def database_unavailable(_request: Request, _error: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Telemetry store unavailable"})


async def check_postgres() -> None:
    """Verify authentication, query execution, and the required PostGIS extension."""
    connection = await psycopg.AsyncConnection.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "sih_eta"),
        user=os.getenv("POSTGRES_USER", "sih_eta"),
        password=os.getenv("POSTGRES_PASSWORD", "sih_eta_local"),
        connect_timeout=3,
    )
    async with connection:
        await connection.execute("SELECT postgis_version()")
        cursor = await connection.execute("SELECT 1 FROM routes LIMIT 1")
        if await cursor.fetchone() is None:
            raise RuntimeError("Static network has not been seeded")


async def check_redis() -> None:
    async with Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        socket_connect_timeout=3,
        socket_timeout=3,
    ) as client:
        await client.ping()


@app.get("/health", tags=["infrastructure"])
async def health() -> dict[str, str]:
    """Liveness: the API process is responding."""
    return {"status": "ok"}


@app.get("/ready", tags=["infrastructure"], responses={503: {"description": "Not ready"}})
async def ready() -> JSONResponse:
    """Readiness: both backing services are reachable; never expose connection secrets."""
    results = await asyncio.gather(
        asyncio.wait_for(check_postgres(), timeout=4),
        asyncio.wait_for(check_redis(), timeout=4),
        return_exceptions=True,
    )
    dependencies = {
        name: "unavailable" if isinstance(result, BaseException) else "ok"
        for name, result in zip(("postgres", "redis"), results, strict=True)
    }
    is_ready = all(status == "ok" for status in dependencies.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ok" if is_ready else "unavailable", "dependencies": dependencies},
    )
