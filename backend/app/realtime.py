"""Redis notifications, per-train state cache and a shared ingestion budget."""

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from pydantic import AwareDatetime, BaseModel, ValidationError
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.eta import get_route, latest_position, route_stops, train_status
from app.models import LivePosition
from app.read_schemas import PositionOut, TrainSummary
from app.schemas import EventIn, PositionIn
from app.seed import load_dataset

KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "sih-eta:v1")
CACHE_SECONDS = 60
RATE_LIMIT = int(os.getenv("INGEST_RATE_LIMIT_PER_MINUTE", "120"))
MAX_BODY_BYTES = 16 * 1024
if RATE_LIMIT < 1:
    raise ValueError("INGEST_RATE_LIMIT_PER_MINUTE must be positive")

# Generation prevents a cache fill that raced a committed write from restoring old state.
NOTIFY_POSITION = """
local revision = redis.call('INCR', KEYS[1])
redis.call('DEL', KEYS[2])
redis.call('PUBLISH', KEYS[3], ARGV[1])
return revision
"""
CACHE_WRITE = """
if (redis.call('GET', KEYS[1]) or '0') ~= ARGV[1] then return 0 end
local old = redis.call('GET', KEYS[2])
if old then
  local ok, entry = pcall(cjson.decode, old)
  if ok and type(entry) == 'table' and type(entry.built_at) == 'string'
     and entry.built_at > ARGV[4] then return 0 end
end
redis.call('SET', KEYS[2], ARGV[2], 'PX', ARGV[3])
return 1
"""
CACHE_DISCARD = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""
RATE_CHECK = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
local ttl = redis.call('PTTL', KEYS[1])
if used >= tonumber(ARGV[1]) then return {0, math.max(ttl, 1)} end
redis.call('INCR', KEYS[1])
if ttl < 0 then redis.call('PEXPIRE', KEYS[1], 60000); ttl = 60000 end
return {1, ttl}
"""


def utc_now() -> datetime:
    return datetime.now(UTC)


def redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


@lru_cache
def get_redis() -> Redis:
    # Sync requests run in FastAPI's thread pool, sharing a bounded connection pool.
    return Redis.from_url(
        redis_url(),
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        max_connections=32,
    )


def channel(train_number: str) -> str:
    return f"{KEY_PREFIX}:trains:{train_number}"


def state_keys(train_number: str) -> tuple[str, str]:
    base = channel(train_number)
    return f"{base}:revision", f"{base}:state"


def check_rate(peer: str) -> tuple[bool, int]:
    # Only the socket peer is trusted; no caller-supplied forwarding headers.
    digest = hashlib.sha256(peer.encode()).hexdigest()
    allowed, ttl_ms = get_redis().eval(RATE_CHECK, 1, f"{KEY_PREFIX}:rate:{digest}", RATE_LIMIT)
    return bool(allowed), max(1, (int(ttl_ms) + 999) // 1000)


class CacheEntry(BaseModel):
    built_at: AwareDatetime
    valid_until: AwareDatetime
    train: TrainSummary


@lru_cache
def train_numbers() -> tuple[str, ...]:
    # This is the same version-checked fixture used by the startup seed, not a DB scan.
    return tuple(sorted(route["train_number"] for route in load_dataset()["routes"]))


def read_train_state(session: Session, number: str, now: datetime) -> CacheEntry:
    route = get_route(session, number)
    stops = route_stops(session, route)
    position = latest_position(session, number, now)
    next_timestamp = session.scalar(
        select(LivePosition.timestamp)
        .where(
            LivePosition.train_number == number,
            LivePosition.timestamp > now,
        )
        .order_by(LivePosition.timestamp)
        .limit(1)
    )
    valid_until = now + timedelta(seconds=CACHE_SECONDS)
    if next_timestamp is not None:
        valid_until = min(valid_until, next_timestamp)
    return CacheEntry(
        built_at=now,
        valid_until=valid_until,
        train=TrainSummary(
            train_number=number,
            train_name=route.train_name,
            origin=stops[0].station_code,
            destination=stops[-1].station_code,
            status=train_status(position, now),
            latest_position=PositionOut.model_validate(position) if position else None,
        ),
    )


def fill_state(session: Session, number: str, now: datetime, revision: str) -> CacheEntry:
    entry = read_train_state(session, number, now)
    # Canonical microsecond UTC strings also order concurrent fills within one generation.
    data = entry.model_dump(mode="json")
    data["built_at"] = now.astimezone(UTC).isoformat(timespec="microseconds")
    get_redis().eval(
        CACHE_WRITE,
        2,
        *state_keys(number),
        revision,
        json.dumps(data),
        max(1, int((entry.valid_until - now).total_seconds() * 1000)),
        data["built_at"],
    )
    return entry


def cached_train(session: Session, number: str, now: datetime) -> TrainSummary:
    revision, raw = get_redis().mget(state_keys(number))
    entry = None
    if raw is not None:
        try:
            candidate = CacheEntry.model_validate_json(raw)
            if (
                candidate.train.train_number == number
                and candidate.built_at <= now < candidate.valid_until
            ):
                entry = candidate
        except (ValidationError, ValueError):
            # Remove only the invalid value we read; do not delete a concurrent repair.
            get_redis().eval(CACHE_DISCARD, 1, state_keys(number)[1], raw)
    if entry is None:
        entry = fill_state(session, number, now, revision or "0")
    row = entry.train
    return row.model_copy(update={"status": train_status(row.latest_position, now)})


def publish_committed(session: Session, payload: PositionIn | EventIn) -> None:
    """Called only after commit, including UUID retries after a delivery failure."""
    client = get_redis()
    number = payload.train_number
    if isinstance(payload, PositionIn):
        revision = client.eval(
            NOTIFY_POSITION, 3, *state_keys(number), channel(number), payload.model_dump_json()
        )
        fill_state(session, number, utc_now(), str(revision))
    else:
        client.publish(channel(number), payload.model_dump_json())


@asynccontextmanager
async def subscribe(number: str) -> AsyncIterator[asyncio.Queue]:
    """Subscribe before the initial SQL snapshot. Coalesce bursts without an unbounded queue."""
    async with (
        AsyncRedis.from_url(
            redis_url(),
            socket_connect_timeout=0.5,
            socket_timeout=1,
            health_check_interval=5,
            decode_responses=True,
        ) as client,
        client.pubsub() as subscription,
    ):
        await subscription.subscribe(channel(number))
        # subscribe() only sends a command; wait for Redis's acknowledgement to close
        # the snapshot/subscription race (otherwise an update could be missed).
        async with asyncio.timeout(2):
            while True:
                ack = await subscription.get_message(timeout=1)
                if ack and ack["type"] == "subscribe":
                    break
        queue = asyncio.Queue(maxsize=1)

        async def listen() -> None:
            try:
                while True:
                    message = await subscription.get_message(
                        ignore_subscribe_messages=True, timeout=1
                    )
                    if message and not queue.full():
                        queue.put_nowait(True)
            except Exception as error:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(error)

        listener = asyncio.create_task(listen())
        try:
            yield queue
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
