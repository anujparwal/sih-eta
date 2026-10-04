"""Stateless hypothetical experiments using the reviewed model; never writes telemetry."""

from datetime import UTC, datetime
from typing import Annotated, Literal

import xgboost as xgb
from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.inference import get_predictor
from app.read_schemas import Features, ModelExplanation

router = APIRouter(prefix="/demo", tags=["Synthetic experiment lab"])


class ScenarioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_delay_minutes: float = Field(15, ge=0, le=180, allow_inf_nan=False)
    distance_km: float = Field(20, ge=0.1, le=500, allow_inf_nan=False)
    elapsed_minutes: float = Field(15, ge=0, le=600, allow_inf_nan=False)
    event_severity: int = Field(0, ge=0, le=3)
    nearby_trains: int = Field(0, ge=0, le=5)


class ScenarioPrediction(BaseModel):
    method: Literal["xgboost", "current_delay_carryover"]
    predicted_delay_minutes: float
    reason: Literal["model_ready", "outside_training_domain", "model_unavailable"]
    explanation: ModelExplanation | None = None


class EvaluationEvidence(BaseModel):
    model_version: str
    baseline_mae_minutes: float
    model_mae_minutes: float
    baseline_rmse_minutes: float
    model_rmse_minutes: float
    training_journeys: int
    validation_journeys: int
    test_journeys: int
    test_rows: int
    model_sha256: str


class ScenarioResult(BaseModel):
    source: Literal["hypothetical_synthetic"] = "hypothetical_synthetic"
    inputs: ScenarioInput
    baseline_delay_minutes: float
    reference: ScenarioPrediction
    scenario: ScenarioPrediction
    evidence: EvaluationEvidence | None
    assumption: str = "Fixed Thursday 12:00 IST. Reference has no active event and no nearby train."
    limitation: str = (
        "Hypothetical next-station delay, not a live ETA or an operational recommendation. "
        "Changing an input shows model sensitivity, not causal impact. Synthetic evaluation "
        "does not establish real railway accuracy; no calibrated prediction interval is available."
    )


def features_for(inputs: ScenarioInput, reference: bool = False) -> Features:
    severity = 0 if reference else inputs.event_severity
    return Features(
        as_of=datetime(2026, 1, 1, 6, 30, tzinfo=UTC),
        minutes_since_last_station=inputs.elapsed_minutes,
        distance_remaining_next_station_km=inputs.distance_km,
        current_delay_minutes=inputs.current_delay_minutes,
        historical_avg_delay_minutes=None,
        historical_sample_count=0,
        historical_station_code=None,
        historical_day_of_week=3,
        historical_hour_of_day=12,
        active_event_count=int(severity > 0),
        active_event_severity_sum=severity,
        active_event_max_severity=severity,
        congestion_index=0 if reference else inputs.nearby_trains,
        congestion_radius_km=10,
        missing=["historical_avg_delay_minutes"],
    )


@router.get("/scenario", response_model=ScenarioResult)
def experiment(response: Response, inputs: Annotated[ScenarioInput, Query()]) -> ScenarioResult:
    response.headers["Cache-Control"] = "no-store"
    predictor = get_predictor()

    def evaluate(reference: bool) -> ScenarioPrediction:
        explanation = None
        reason = "model_unavailable"
        if predictor:
            try:
                explanation = predictor.explain(features_for(inputs, reference))
                reason = "model_ready" if explanation else "outside_training_domain"
            except (ValueError, xgb.core.XGBoostError):
                pass  # Keep the independent baseline without exposing internal errors.
        return ScenarioPrediction(
            method="xgboost" if explanation else "current_delay_carryover",
            predicted_delay_minutes=(
                explanation.predicted_delay_minutes if explanation else inputs.current_delay_minutes
            ),
            reason=reason,
            explanation=explanation,
        )

    evidence = None
    if predictor:
        metadata = predictor.metadata
        scores, split = metadata["test_metrics"], metadata["split"]
        evidence = EvaluationEvidence(
            model_version=predictor.version,
            baseline_mae_minutes=scores["baseline"]["mae_minutes"],
            model_mae_minutes=scores["xgboost"]["mae_minutes"],
            baseline_rmse_minutes=scores["baseline"]["rmse_minutes"],
            model_rmse_minutes=scores["xgboost"]["rmse_minutes"],
            training_journeys=split["train"]["journeys"],
            validation_journeys=split["validation"]["journeys"],
            test_journeys=split["test"]["journeys"],
            test_rows=split["test"]["rows"],
            model_sha256=metadata["model_sha256"],
        )
    return ScenarioResult(
        inputs=inputs,
        baseline_delay_minutes=inputs.current_delay_minutes,
        reference=evaluate(True),
        scenario=evaluate(False),
        evidence=evidence,
    )
