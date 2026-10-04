"""Experiments must use the shipped model without touching live services."""

import asyncio

import httpx
import pytest

from app import demo
from app.inference import get_predictor
from app.main import app


def get(query=""):
    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/demo/scenario" + query)

    return asyncio.run(request())


def test_real_model_comparison_and_explanation_reconcile():
    response = get("?event_severity=3")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["source"] == "hypothetical_synthetic"
    assert body["baseline_delay_minutes"] == 15
    model = get_predictor()
    for name, reference in [("scenario", False), ("reference", True)]:
        output = body[name]
        assert output["method"] == "xgboost"
        expected = model.explain(demo.features_for(demo.ScenarioInput(event_severity=3), reference))
        assert output["predicted_delay_minutes"] == expected.predicted_delay_minutes
        explanation = output["explanation"]
        total = (
            15
            + explanation["base_value_minutes"]
            + explanation["clipping_adjustment_minutes"]
            + sum(c["contribution_minutes"] for c in explanation["contributions"])
        )
        assert total == pytest.approx(output["predicted_delay_minutes"], abs=0.001)
    assert (
        body["evidence"]["model_mae_minutes"]
        == model.metadata["test_metrics"]["xgboost"]["mae_minutes"]
    )
    assert body["evidence"]["test_journeys"] == 24
    assert get("?event_severity=3").json() == body  # Reproducible without time or live data.


def test_quiet_reference_matches_scenario_and_preserves_missing_history():
    body = get().json()
    assert body["reference"] == body["scenario"]
    features = demo.features_for(demo.ScenarioInput(event_severity=2))
    assert features.active_event_count == 1
    assert features.active_event_severity_sum == features.active_event_max_severity == 2
    assert features.historical_avg_delay_minutes is None
    assert features.as_of.utcoffset().total_seconds() == 0


def test_out_of_domain_only_falls_back_for_unsupported_input():
    body = get("?nearby_trains=3").json()
    assert body["reference"]["method"] == "xgboost"
    assert body["scenario"] == {
        "method": "current_delay_carryover",
        "predicted_delay_minutes": 15,
        "reason": "outside_training_domain",
        "explanation": None,
    }
    body = get("?distance_km=500").json()
    assert body["reference"]["reason"] == body["scenario"]["reason"] == "outside_training_domain"


def test_disabled_model_uses_baseline_without_fake_evidence(monkeypatch):
    monkeypatch.setattr(demo, "get_predictor", lambda: None)
    body = get().json()
    assert body["evidence"] is None
    assert body["scenario"]["reason"] == "model_unavailable"
    assert body["reference"]["predicted_delay_minutes"] == 15


def test_prediction_failure_is_sanitized(monkeypatch):
    class Broken:
        metadata = get_predictor().metadata
        version = "test-model"

        def explain(self, features):
            raise ValueError("internal-secret")

    monkeypatch.setattr(demo, "get_predictor", Broken)
    response = get()
    assert response.status_code == 200
    assert response.json()["scenario"]["reason"] == "model_unavailable"
    assert "internal-secret" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "current_delay_minutes=-1",
        "distance_km=0",
        "distance_km=501",
        "elapsed_minutes=601",
        "event_severity=4",
        "event_severity=1.5",
        "nearby_trains=6",
        "current_delay_minutes=nan",
        "distance_km=inf",
        "elapsed_minutes=oops",
        "train_number=12301",
    ],
)
def test_invalid_experiments_never_run_model(monkeypatch, query):
    def forbidden():
        pytest.fail("Invalid input reached the predictor")

    monkeypatch.setattr(demo, "get_predictor", forbidden)
    assert get("?" + query).status_code == 422
