"""On-demand RailRadar reads, independent of the synthetic fleet and ETA model."""

import hashlib
import json
import os
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import APIRouter, HTTPException, Path, Query, Response
from pydantic import AliasChoices, AwareDatetime, BaseModel, Field, ValidationError
from redis.exceptions import LockError

from app import realtime

router = APIRouter(prefix="/live", tags=["RailRadar live data"])
CACHE_SECONDS = 300
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
BUDGET = """
if tonumber(redis.call('GET', KEYS[1]) or '0') >= tonumber(ARGV[1])
or tonumber(redis.call('GET', KEYS[2]) or '0') >= tonumber(ARGV[2]) then return 0 end
redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], 172800)
redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], 2764800)
return 1
"""


class ProviderModel(BaseModel):
    model_config = {"populate_by_name": True}


class Station(ProviderModel):
    station_code: str | None = Field(None, validation_alias=AliasChoices("stationCode", "code"))
    station_name: str | None = Field(None, validation_alias=AliasChoices("stationName", "name"))


class Location(Station):
    status: str | None = None
    is_actual_position: bool | None = Field(None, validation_alias="isActualPosition")


class Stop(Station):
    sequence: int
    is_halt: bool | None = Field(None, validation_alias="isHalt")
    status: str | None = None
    scheduled_arrival: AwareDatetime | None = Field(None, validation_alias="scheduledArrival")
    scheduled_departure: AwareDatetime | None = Field(None, validation_alias="scheduledDeparture")
    # Upstream's actual* fields can contain future estimates. Never label them as observed.
    reported_arrival: AwareDatetime | None = Field(None, validation_alias="actualArrival")
    reported_departure: AwareDatetime | None = Field(None, validation_alias="actualDeparture")
    platform: str | int | None = None


class ExceptionNotice(BaseModel):
    type: str | None = None
    message: str | None = None


class TrainInfo(BaseModel):
    source: Station | None = None
    destination: Station | None = None


class ProviderTrain(ProviderModel):
    train_number: str = Field(pattern=r"^[0-9]{5}$", validation_alias="trainNumber")
    train_name: str | None = Field(None, validation_alias="trainName")
    journey_start_date: date | None = Field(None, validation_alias="startDate")
    updated_at: AwareDatetime | None = Field(None, validation_alias="lastUpdatedAt")
    status: str | None = None
    delay_minutes: float | None = Field(None, validation_alias="delayMinutes", allow_inf_nan=False)
    is_live: bool | None = Field(None, validation_alias="isLive")
    tracking_mode: str | None = Field(None, validation_alias="trackingMode")
    train: TrainInfo | None = None
    current_location: Location | None = Field(None, validation_alias="currentLocation")
    next_halt: Station | None = Field(None, validation_alias="nextHalt")
    route: list[Stop] = Field(default_factory=list, max_length=1500)
    exceptions: list[ExceptionNotice] = Field(default_factory=list, max_length=100)


class LiveResult(BaseModel):
    source: Literal["railradar"] = "railradar"
    fetched_at: AwareDatetime
    cached: bool = False
    freshness: Literal["recent", "stale", "unknown", "not_live"] = "unknown"
    warning: str | None = None
    cache_seconds: int = CACHE_SECONDS
    data: ProviderTrain


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the secret to another host.


def fetch_provider(number: str, journey_date: date, key: str) -> ProviderTrain:
    query = urlencode({"date": journey_date.isoformat()})
    request = Request(
        f"https://api.railradar.in/v1/trains/{number}/live?{query}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=12) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("Oversized response")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ValueError("Unsuccessful response")
        data = ProviderTrain.model_validate(payload.get("data"))
        if data.train_number != number or (
            data.journey_start_date is not None and data.journey_start_date != journey_date
        ):
            raise ValueError("Mismatched journey")
        return data
    except HTTPError as error:
        error.close()
        if error.code == 404:
            raise HTTPException(
                404, "No RailRadar data for this train and journey start date."
            ) from None
        if error.code in {401, 403}:
            raise HTTPException(
                503, "RailRadar rejected the server API key or plan access."
            ) from None
        if error.code == 429:
            raise HTTPException(429, "RailRadar request quota reached. Try again later.") from None
        raise HTTPException(503, "RailRadar is temporarily unavailable.") from None
    except (URLError, TimeoutError, OSError, ValueError, ValidationError):
        raise HTTPException(503, "RailRadar returned unavailable or invalid train data.") from None


def decorate(
    result: LiveResult, now: datetime, cached: bool, warning: str | None = None
) -> LiveResult:
    age = (now - result.data.updated_at).total_seconds() if result.data.updated_at else None
    freshness = (
        "not_live"
        if result.data.is_live is False
        else "unknown"
        if age is None or age < -60 or result.data.is_live is None
        else "stale"
        if warning or age > 600
        else "recent"
    )
    return result.model_copy(update={"cached": cached, "freshness": freshness, "warning": warning})


def budget_limit(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        if value > 0:
            return value
    except ValueError:
        pass
    raise HTTPException(503, "RailRadar request budget is not configured correctly.")


@router.get("/trains/{train_number}", response_model=LiveResult)
def live_train(
    response: Response,
    train_number: Annotated[str, Path(pattern=r"^[0-9]{5}$")],
    journey_date: Annotated[date | None, Query(alias="date")] = None,
) -> LiveResult:
    """Accept any five-digit number; provider coverage determines availability."""
    from zoneinfo import ZoneInfo

    response.headers["Cache-Control"] = "no-store"
    key = os.getenv("RAILRADAR_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            503, "RailRadar is not configured. Set RAILRADAR_API_KEY on the backend."
        )
    now = datetime.now(UTC)
    journey_date = journey_date or now.astimezone(ZoneInfo("Asia/Kolkata")).date()
    # Isolate accounts without placing the API key itself in Redis keys or logs.
    account = hashlib.sha256(key.encode()).hexdigest()[:16]
    prefix = f"{realtime.KEY_PREFIX}:railradar:{account}"
    cache_key = f"{prefix}:train:{train_number}:{journey_date}"
    client = realtime.get_redis()
    previous = None
    raw = client.get(cache_key)
    if raw:
        try:
            previous = LiveResult.model_validate_json(raw)
        except ValidationError:
            client.delete(cache_key)
    if previous and 0 <= (now - previous.fetched_at).total_seconds() < CACHE_SECONDS:
        return decorate(previous, now, True)

    def unavailable(status: int, detail: str) -> LiveResult:
        if previous:
            return decorate(previous, now, True, detail)
        raise HTTPException(status, detail, headers={"Retry-After": "60"})

    try:
        with client.lock(f"{cache_key}:lock", timeout=30, blocking_timeout=0.2):
            # Another worker may have filled the shared cache while this request waited.
            raw = client.get(cache_key)
            if raw:
                entry = LiveResult.model_validate_json(raw)
                if 0 <= (now - entry.fetched_at).total_seconds() < CACHE_SECONDS:
                    return decorate(entry, now, True)
            for error_key in (f"{prefix}:cooldown", f"{cache_key}:error"):
                error = client.get(error_key)
                if error:
                    status, detail = json.loads(error)
                    return unavailable(status, detail)
            allowed = client.eval(
                BUDGET,
                2,
                f"{prefix}:day:{now:%Y-%m-%d}",
                f"{prefix}:month:{now:%Y-%m}",
                budget_limit("RAILRADAR_DAILY_LIMIT", 30),
                budget_limit("RAILRADAR_MONTHLY_LIMIT", 900),
            )
            if not allowed:
                return unavailable(429, "Local RailRadar request budget reached. Cached data only.")
            try:
                data = fetch_provider(train_number, journey_date, key)
            except HTTPException as error:
                target = f"{cache_key}:error" if error.status_code == 404 else f"{prefix}:cooldown"
                client.set(target, json.dumps([error.status_code, error.detail]), ex=60)
                return unavailable(error.status_code, error.detail)
            result = LiveResult(fetched_at=datetime.now(UTC), data=data)
            client.set(cache_key, result.model_dump_json(), ex=86400)
            return decorate(result, datetime.now(UTC), False)
    except LockError:
        return unavailable(429, "A lookup for this train is in progress. Try again shortly.")
