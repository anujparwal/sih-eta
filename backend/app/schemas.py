"""The Phase 2 ingest contract. All timestamps carry an explicit UTC offset."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Telemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: UUID
    journey_id: UUID
    train_number: str = Field(pattern=r"^\d{5}$")
    timestamp: AwareDatetime
    source: Literal["simulator"] = "simulator"

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class PositionIn(Telemetry):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    distance_km: float = Field(ge=0)
    delay_minutes: float = Field(ge=0)
    current_speed_kmh: float = Field(ge=0, le=200)
    last_station: str = Field(pattern=r"^[A-Z0-9]{1,10}$")
    next_station: str | None = Field(default=None, pattern=r"^[A-Z0-9]{1,10}$")


class EventIn(Telemetry):
    event_type: Literal["speed_restriction", "unscheduled_stop", "congestion", "weather"]
    severity: int = Field(ge=1, le=3)
    description: str = Field(min_length=1, max_length=500)
    duration_seconds: int = Field(ge=1, le=3600)


class IngestResult(BaseModel):
    id: UUID
    status: Literal["created", "duplicate"]
