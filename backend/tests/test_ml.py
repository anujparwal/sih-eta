"""Artifact checks, serving explanations, leakage boundaries and training/serving parity."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from app import inference
from app.features import feature_values
from app.model_features import FEATURE_NAMES, feature_vector
from app.models import HistoricalDelay, LivePosition, RouteStop
from app.read_schemas import Features
from ml.dataset import Example, chronological_split, examples_from_records
from ml.refresh_history import aggregates, refresh
from ml.train import forecast, metrics
from simulator.engine import Fleet


@pytest.fixture
def model_features():
    return Features.model_validate(
        json.loads((Path(__file__).parent / "examples/eta.json").read_text())["features"]
    )


def test_reviewed_artifact_prediction_and_exact_shap_sum(model_features):
    predictor = inference.Predictor(inference.DEFAULT_MODEL_DIR)
    result = predictor.explain(model_features)
    assert result is not None
    assert sum(
        c.contribution_minutes for c in result.contributions
    ) + result.base_value_minutes == pytest.approx(result.raw_residual_minutes, abs=0.001)
    assert result.predicted_delay_minutes == pytest.approx(
        result.current_delay_minutes
        + result.raw_residual_minutes
        + result.clipping_adjustment_minutes
    )
    assert result.predicted_delay_minutes == predictor.predict(model_features)
    assert [c.feature for c in result.contributions] == FEATURE_NAMES
    assert (
        predictor.metadata["test_metrics"]["xgboost"]["mae_minutes"]
        < predictor.metadata["test_metrics"]["baseline"]["mae_minutes"] * 0.9
    )


def test_missing_features_stay_nan_and_unseen_values_fall_back(model_features):
    predictor = inference.Predictor(inference.DEFAULT_MODEL_DIR)
    model_features.minutes_since_last_station = None
    assert np.isnan(feature_vector(model_features)[0])
    assert predictor.explain(model_features) is not None
    model_features.congestion_index = 10
    assert predictor.explain(model_features) is None
    model_features.current_delay_minutes = float("inf")
    with pytest.raises(ValueError, match="Nonfinite"):
        feature_vector(model_features)


@pytest.mark.parametrize("change", ["checksum", "features", "acceptance", "network", "objective"])
def test_model_rejects_unreviewed_or_incompatible_artifact(tmp_path, change):
    import shutil

    shutil.copytree(inference.DEFAULT_MODEL_DIR, tmp_path / "models")
    path = tmp_path / "models/metadata.json"
    metadata = json.loads(path.read_text())
    if change == "checksum":
        metadata["model_sha256"] = "0" * 64
    elif change == "features":
        metadata["features"] = list(reversed(FEATURE_NAMES))
    elif change == "acceptance":
        metadata["acceptance_passed"] = False
    elif change == "network":
        metadata["network_sha256"] = "0" * 64
    else:
        metadata["target"] = "wrong"
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        inference.Predictor(tmp_path / "models")


def test_unavailable_model_load_is_cached_and_disabled_is_explicit(monkeypatch, tmp_path):
    inference.get_predictor.cache_clear()
    monkeypatch.setenv("ETA_MODEL_DIR", str(tmp_path))
    try:
        assert inference.get_predictor() is None
        assert inference.get_predictor() is None
        assert inference.get_predictor.cache_info().hits == 1
        inference.get_predictor.cache_clear()
        monkeypatch.setenv("ETA_MODEL_ENABLED", "false")
        assert inference.get_predictor() is None
    finally:
        inference.get_predictor.cache_clear()


def records(dataset):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    train = Fleet(dataset, start, 42).trains[0]
    points = []
    # The label is station arrival delay (five minutes), not the next row's delay.
    for elapsed, clock in [(0, 0), (1320, 1150), (1380, 1190), (1500, 1200), (61800, 61500)]:
        train.elapsed, train.clock = elapsed, clock
        points.append(train.snapshot())
    event = {
        "id": str(uuid4()),
        "journey_id": train.journey_id,
        "train_number": "12301",
        "timestamp": (start + timedelta(seconds=1370)).isoformat(),
        "event_type": "weather",
        "severity": 2,
        "duration_seconds": 120,
        "description": "Synthetic test event",
        "source": "simulator",
    }
    return {"positions": points, "events": [event], "historical_delays": []}


def test_observed_station_target_and_shared_asof_arithmetic(dataset):
    data = records(dataset)
    examples = examples_from_records(data)
    row = next(e for e in examples if e.features.active_event_count == 1)
    assert row.target == 5
    assert row.features.current_delay_minutes == pytest.approx(190 / 60)
    assert row.label_at > row.features.as_of
    assert row.features.historical_avg_delay_minutes is None
    assert row.features.minutes_since_last_station == 23
    assert row.features.active_event_max_severity == 2
    future_event = dict(
        data["events"][0],
        id=str(uuid4()),
        severity=3,
        timestamp=(row.features.as_of + timedelta(seconds=1)).isoformat(),
    )
    data["events"].append(future_event)
    repeated = next(
        e for e in examples_from_records(data) if e.features.as_of == row.features.as_of
    )
    assert repeated.features == row.features
    history = HistoricalDelay(avg_delay_minutes=999, sample_count=99)
    point = LivePosition(**{**data["positions"][2], "timestamp": row.features.as_of})
    upcoming = RouteStop(**dataset["routes"][0]["stops"][1])
    with_history = feature_values(point, upcoming, row.journey_started_at, history, [], [])
    assert with_history.historical_avg_delay_minutes == 999
    assert "historical_avg_delay_minutes" not in FEATURE_NAMES


def test_time_split_purges_crossing_journeys_and_never_splits_one(model_features):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for day in range(10):
        at = start + timedelta(days=day)
        row = Example(
            "12301",
            uuid4(),
            at,
            at + timedelta(hours=1),
            at + timedelta(minutes=30),
            "DKAE",
            at + timedelta(minutes=20),
            model_features.model_copy(update={"as_of": at}),
            10,
        )
        rows.extend([row, replace(row, target=11)])
    rows[8] = replace(rows[8], journey_ended_at=start + timedelta(days=7))
    rows[9] = replace(rows[9], journey_ended_at=start + timedelta(days=7))
    train, valid, test = chronological_split(rows)
    groups = [{e.journey_id for e in split} for split in (train, valid, test)]
    assert not groups[0] & groups[1] and not groups[0] & groups[2] and not groups[1] & groups[2]
    assert rows[8].journey_id not in set.union(*groups)
    assert max(e.journey_ended_at for e in train) < min(e.journey_started_at for e in valid)
    assert max(e.journey_ended_at for e in valid) < min(e.journey_started_at for e in test)


def test_evaluation_uses_deployed_prediction_and_fallback(model_features):
    predictor = inference.Predictor(inference.DEFAULT_MODEL_DIR)
    as_of = model_features.as_of
    row = Example(
        "12301",
        uuid4(),
        as_of,
        as_of + timedelta(hours=1),
        as_of + timedelta(minutes=30),
        "DKAE",
        as_of + timedelta(minutes=10),
        model_features,
        10,
    )
    assert forecast(predictor.booster, [row])[0] == pytest.approx(predictor.predict(model_features))
    model_features.congestion_index = 10
    assert forecast(predictor.booster, [row])[0] == model_features.current_delay_minutes
    assert metrics(np.array([1.0, 3.0]), np.array([2.0, 1.0])) == {
        "mae_minutes": 1.5,
        "rmse_minutes": np.sqrt(2.5),
    }


def test_offline_and_database_features_match_as_of_sample(db, dataset):
    from geoalchemy2 import WKTElement

    from app.features import compute_features
    from ml.dataset import objects

    data = records(dataset)
    positions, events = objects(data)
    for point in positions:
        point.geom = WKTElement(f"POINT({point.lon} {point.lat})", srid=4326)
        db.add(point)
    for event in events:
        db.add(event)
    db.flush()
    stops = [RouteStop(**s) for s in dataset["routes"][0]["stops"]]
    point = positions[2]
    online = compute_features(db, point, stops)
    offline = next(
        e.features for e in examples_from_records(data) if e.features.as_of == point.timestamp
    )
    assert online == offline
    rows = refresh(db, positions[3].timestamp + timedelta(seconds=1), apply=True)
    assert len(rows) == 1 and rows[0]["avg_delay_minutes"] == 5
    assert refresh(db, positions[3].timestamp + timedelta(seconds=1), apply=True) == rows
    assert len(list(db.query(HistoricalDelay))) == 1
    assert refresh(db, positions[2].timestamp) == []


def test_history_counts_each_arrival_once_and_skips_sparse_data(dataset):
    from ml.dataset import objects

    data = records(dataset)
    points, _ = objects(data)
    result = aggregates(points)
    assert len(result) == 1 and result[0]["sample_count"] == 1
    assert result[0]["avg_delay_minutes"] == 5
    data["positions"].pop(2)
    points, _ = objects(data)
    assert aggregates(points) == []
