"""Load a reviewed JSON artifact once; baseline remains available if ML cannot serve safely."""

import hashlib
import json
import logging
import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import xgboost as xgb

from app.model_features import FEATURE_NAMES, FEATURE_VERSION, feature_vector
from app.read_schemas import Features, ModelExplanation, ShapContribution
from app.seed import DATA_PATH

LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "ml" / "models"
if not DEFAULT_MODEL_DIR.exists():
    DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[1] / "ml" / "models"


class Predictor:
    def __init__(self, directory: Path):
        self.metadata = json.loads((directory / "metadata.json").read_text())
        model_path = directory / "eta_model.json"
        metadata = self.metadata
        if (
            metadata["features"] != FEATURE_NAMES
            or metadata["feature_version"] != FEATURE_VERSION
            or metadata["target"] != "next_station_delay_minus_current_delay_minutes"
            or metadata["acceptance_passed"] is not True
            or metadata["provenance"]["kind"] != "synthetic"
            or metadata["model_sha256"] != hashlib.sha256(model_path.read_bytes()).hexdigest()
            or metadata["network_sha256"] != hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()
        ):
            raise ValueError("Incompatible or unapproved model artifact")
        self.booster = xgb.Booster(params={"nthread": 1})
        self.booster.load_model(model_path)
        self.booster.set_param({"nthread": 1})
        config = json.loads(self.booster.save_config())["learner"]
        if (
            self.booster.feature_names != FEATURE_NAMES
            or config["objective"]["name"] != "reg:squarederror"
            or config["gradient_booster"]["name"] != "gbtree"
        ):
            raise ValueError("Model feature order or objective is incompatible")
        self.version = metadata["model_version"]
        self.ranges = metadata["training_ranges"]
        if set(self.ranges) != set(FEATURE_NAMES) or not all(
            len(bounds) == 2 and all(math.isfinite(v) for v in bounds) and bounds[0] <= bounds[1]
            for bounds in self.ranges.values()
        ):
            raise ValueError("Invalid model domain metadata")

    def explain(self, features: Features) -> ModelExplanation | None:
        vector = feature_vector(features)
        # Missing observed station timing occurs in training and stays NaN. Never impute zero.
        # Refuse numerical extrapolation beyond the measured synthetic training domain.
        for name, value in zip(FEATURE_NAMES, vector, strict=True):
            low, high = self.ranges[name]
            if not math.isnan(value) and not low - 1e-6 <= value <= high + 1e-6:
                return None
        matrix = xgb.DMatrix(
            np.array([vector], dtype=np.float32), feature_names=FEATURE_NAMES, nthread=1
        )
        raw = float(self.booster.predict(matrix)[0])
        contributions = self.booster.predict(matrix, pred_contribs=True)[0]
        if not math.isfinite(raw) or not np.isfinite(contributions).all():
            raise ValueError("Nonfinite model output")
        if abs(float(contributions.sum()) - raw) > 0.001:
            raise ValueError("SHAP contributions do not reconcile with prediction")
        delay = max(0, features.current_delay_minutes + raw)
        return ModelExplanation(
            base_value_minutes=float(contributions[-1]),
            contributions=[
                ShapContribution(
                    feature=name, value=getattr(features, name), contribution_minutes=float(value)
                )
                for name, value in zip(FEATURE_NAMES, contributions[:-1], strict=True)
            ],
            raw_residual_minutes=raw,
            current_delay_minutes=features.current_delay_minutes,
            clipping_adjustment_minutes=delay - features.current_delay_minutes - raw,
            predicted_delay_minutes=delay,
        )

    def predict(self, features: Features) -> float | None:
        explanation = self.explain(features)
        return explanation.predicted_delay_minutes if explanation else None


@lru_cache(maxsize=1)
def get_predictor() -> Predictor | None:
    if os.getenv("ETA_MODEL_ENABLED", "true").lower() == "false":
        return None
    try:
        return Predictor(Path(os.getenv("ETA_MODEL_DIR", str(DEFAULT_MODEL_DIR))))
    except (OSError, ValueError, KeyError, TypeError, xgb.core.XGBoostError):
        LOGGER.warning("ETA model unavailable or incompatible; using carryover baseline")
        return None


def predict(features: Features) -> float | None:
    predictor = get_predictor()
    return predictor.predict(features) if predictor else None
