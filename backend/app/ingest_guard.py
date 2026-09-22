"""Bound ingestion before JSON parsing and apply a Redis budget across API workers."""

import hmac
import json
import math
import os

from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from app import realtime


def invalid_number(_value: str):
    raise ValueError("Non-finite JSON number")


def finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        invalid_number(value)
    return number


class IngestGuard:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/ingest/"):
            await self.app(scope, receive, send)
            return
        key = os.getenv("INGEST_API_KEY", "")
        if key and not hmac.compare_digest(
            dict(scope["headers"]).get(b"authorization", b""), f"Bearer {key}".encode()
        ):
            await JSONResponse(
                {"detail": "Valid ingestion credentials required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        try:
            allowed, retry_after = await run_in_threadpool(
                realtime.check_rate, (scope.get("client") or ("unknown", 0))[0]
            )
        except RedisError:
            await JSONResponse({"detail": "Realtime store unavailable"}, status_code=503)(
                scope, receive, send
            )
            return
        if not allowed:
            await JSONResponse(
                {"detail": "Ingestion rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > realtime.MAX_BODY_BYTES:
                await JSONResponse(
                    {"detail": "Ingestion body exceeds 16384 bytes"}, status_code=413
                )(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        try:
            json.loads(body, parse_constant=invalid_number, parse_float=finite_float)
        except (ValueError, RecursionError):
            await JSONResponse(
                {"detail": "Body must be valid JSON with finite numbers"}, status_code=422
            )(scope, receive, send)
            return
        pending = True

        async def bounded_receive():
            nonlocal pending
            if pending:
                pending = False
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
