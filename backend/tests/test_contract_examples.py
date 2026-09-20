"""The documentation's complete JSON examples must match the public response models."""

import json
from pathlib import Path

import pytest

from app.read_schemas import FleetStatus, JourneyHistory, StationArrivals, TrainETA, TrainList

EXAMPLES = Path(__file__).with_name("examples")


@pytest.mark.parametrize(
    "name,model",
    [
        ("trains", TrainList),
        ("eta", TrainETA),
        ("eta_ml", TrainETA),
        ("history", JourneyHistory),
        ("arrivals", StationArrivals),
        ("fleet_status", FleetStatus),
    ],
)
def test_documented_response_shapes(name, model):
    model.model_validate_json((EXAMPLES / f"{name}.json").read_text())


def test_documented_websocket_matches_rest_eta():
    message = json.loads((EXAMPLES / "websocket.json").read_text())
    assert message["type"] == "eta_update"
    assert message["data"] == json.loads((EXAMPLES / "eta.json").read_text())
    TrainETA.model_validate(message["data"])


def test_documented_ml_websocket_matches_rest_and_reviewed_model():
    from app.inference import get_predictor

    message = json.loads((EXAMPLES / "websocket_ml.json").read_text())
    expected = json.loads((EXAMPLES / "eta_ml.json").read_text())
    assert message["type"] == "eta_update" and message["data"] == expected
    eta = TrainETA.model_validate(expected)
    assert eta.stations[0].explanation == get_predictor().explain(eta.features)
