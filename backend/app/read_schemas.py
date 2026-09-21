"""Versioned read shapes; predictions retain an independent baseline comparison."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import EventIn, PositionIn

Status = Literal["no_data", "active", "stale", "completed"]
TimingBasis = Literal["provided", "inferred_from_first_position", "unavailable"]


class Features(BaseModel):
    as_of: datetime
    minutes_since_last_station: float | None
    distance_remaining_next_station_km: float
    current_delay_minutes: float
    historical_avg_delay_minutes: float | None
    historical_sample_count: int
    historical_station_code: str | None
    historical_day_of_week: int
    historical_hour_of_day: int
    historical_timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    active_event_count: int
    active_event_severity_sum: int
    active_event_max_severity: int
    event_scope: Literal["train_journey"] = "train_journey"
    congestion_index: int
    congestion_radius_km: float
    missing: list[str]


class PositionOut(PositionIn):
    model_config = ConfigDict(from_attributes=True)


class EventOut(EventIn):
    model_config = ConfigDict(from_attributes=True)


class NetworkStation(BaseModel):
    code: str
    name: str
    zone: str | None
    lat: float
    lon: float


class NetworkStop(BaseModel):
    sequence: int
    station_code: str
    arrival_seconds: int | None
    departure_seconds: int | None
    distance_km: float


class NetworkRoute(BaseModel):
    train_number: str
    train_name: str
    total_distance_km: float
    stops: list[NetworkStop]


class NetworkSource(BaseModel):
    url: str
    sha256: str


class Network(BaseModel):
    dataset_version: str
    schedule_timezone: str
    geometry_kind: str
    sources: dict[str, NetworkSource]
    stations: list[NetworkStation]
    routes: list[NetworkRoute]


class TrainSummary(BaseModel):
    train_number: str
    train_name: str
    origin: str
    destination: str
    status: Status
    latest_position: PositionOut | None


class TrainList(BaseModel):
    generated_at: datetime
    source: Literal["simulator"] = "simulator"
    trains: list[TrainSummary]


class ShapContribution(BaseModel):
    feature: str
    value: float | None
    contribution_minutes: float


class ModelExplanation(BaseModel):
    method: Literal["tree_shap"] = "tree_shap"
    target: Literal["next_station_delay_residual_minutes"] = "next_station_delay_residual_minutes"
    base_value_minutes: float
    contributions: list[ShapContribution]
    raw_residual_minutes: float
    current_delay_minutes: float
    clipping_adjustment_minutes: float
    predicted_delay_minutes: float
    interpretation: str = "Model contributions, not causal effects; synthetic training data only."


class StationETA(BaseModel):
    station_code: str
    station_name: str
    sequence: int
    distance_remaining_km: float
    scheduled_arrival: datetime
    baseline_eta: datetime
    eta: datetime
    prediction_method: str = "current_delay_carryover"
    model_version: str | None = None
    eta_baseline_minutes: float | None = None
    eta_ml_minutes: float | None = None
    ml_eta: datetime | None = None
    predicted_delay_minutes: float | None = None
    explanation: ModelExplanation | None = None


class TrainETA(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    source: Literal["simulator"] = "simulator"
    train_number: str
    status: Status
    journey_id: UUID | None
    position_id: UUID | None
    as_of: datetime | None
    journey_started_at: datetime | None
    timing_basis: TimingBasis
    baseline_method: Literal["current_delay_carryover"] = "current_delay_carryover"
    current_delay_minutes: float | None
    features: Features | None
    stations: list[StationETA]
    position: PositionOut | None = None
    active_events: list[EventOut] = Field(default_factory=list)
    eta_baseline_minutes: float | None = None
    eta_ml_minutes: float | None = None
    ml_status: Literal[
        "ready",
        "unavailable",
        "outside_training_domain",
        "legacy_timing",
        "no_next_station",
        "prediction_error",
    ] = "unavailable"


class JourneyHistory(BaseModel):
    generated_at: datetime
    train_number: str
    journey_id: UUID | None
    positions: list[PositionOut]
    next_after: datetime | None


class Arrival(StationETA):
    train_number: str
    train_name: str
    journey_id: UUID
    as_of: datetime
    status: Status
    timing_basis: TimingBasis


class StationArrivals(BaseModel):
    generated_at: datetime
    station_code: str
    source: Literal["simulator"] = "simulator"
    arrivals: list[Arrival]


class FleetStatus(TrainList):
    total_trains: int
    active_trains: int
    stale_trains: int
    completed_trains: int
    no_data_trains: int
    delayed_active_trains: int
    mean_active_delay_minutes: float | None
    max_active_delay_minutes: float | None
