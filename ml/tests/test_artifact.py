"""Load the shipped XGBoost JSON independently of the API; never train in tests."""

import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.inference import Predictor
from app.read_schemas import Features

MODEL_DIR = Path(__file__).resolve().parents[1] / "models"


def known_input():
    return Features(
        as_of=datetime(2026, 9, 17, 18, 40, tzinfo=UTC),
        minutes_since_last_station=None,
        distance_remaining_next_station_km=0.789473684210634,
        current_delay_minutes=5,
        historical_avg_delay_minutes=None,
        historical_sample_count=0,
        historical_station_code="NDLS",
        historical_day_of_week=4,
        historical_hour_of_day=0,
        active_event_count=0,
        active_event_severity_sum=0,
        active_event_max_severity=0,
        congestion_index=0,
        congestion_radius_km=5,
        missing=["minutes_since_last_station", "historical_avg_delay_minutes"],
    )


def test_shipped_model_loads_and_predicts_a_finite_positive_delay():
    value = Predictor(MODEL_DIR).predict(known_input())
    assert value is not None and math.isfinite(value)
    # A near-arrival sample already five minutes late should yield minutes, not
    # seconds, a negative delay, or an implausible day-long prediction.
    assert 1 < value < 30
    assert Predictor(MODEL_DIR).predict(known_input()) == pytest.approx(value, abs=1e-6)


def test_corrupted_model_bytes_are_rejected_before_serving(tmp_path):
    copied = tmp_path / "models"
    shutil.copytree(MODEL_DIR, copied)
    (copied / "eta_model.json").write_text('{"corrupted":true}')
    with pytest.raises(ValueError, match="Incompatible or unapproved"):
        Predictor(copied)
