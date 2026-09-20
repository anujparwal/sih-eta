"""Train a CPU XGBoost residual model; select on validation and evaluate once on later journeys."""

import argparse
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import xgboost as xgb

from app.model_features import FEATURE_NAMES, FEATURE_VERSION, feature_vector
from app.seed import DATA_PATH
from ml.dataset import Example, chronological_split, examples_from_records


def matrix(examples: list[Example]) -> xgb.DMatrix:
    return xgb.DMatrix(
        np.array([feature_vector(e.features) for e in examples], dtype=np.float32),
        feature_names=FEATURE_NAMES,
        nthread=1,
    )


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    error = predicted - actual
    return {
        "mae_minutes": float(np.abs(error).mean()),
        "rmse_minutes": float(np.sqrt(np.square(error).mean())),
    }


def forecast(booster: xgb.Booster, examples: list[Example]) -> np.ndarray:
    current = np.array([e.features.current_delay_minutes for e in examples])
    values = np.array([feature_vector(e.features) for e in examples])
    ranges = json.loads(booster.attr("training_ranges"))
    supported = np.ones(len(examples), dtype=bool)
    for i, name in enumerate(FEATURE_NAMES):
        low, high = ranges[name]
        supported &= np.isnan(values[:, i]) | (
            (values[:, i] >= low - 1e-6) & (values[:, i] <= high + 1e-6)
        )
    minimum = np.array(
        [max(0, (e.features.as_of - e.scheduled_arrival).total_seconds() / 60) for e in examples]
    )
    predicted = np.maximum(minimum, current + booster.predict(matrix(examples)))
    return np.where(supported, predicted, current)


def evaluate(booster: xgb.Booster, examples: list[Example]) -> dict:
    actual = np.array([e.target for e in examples])
    current = np.array([e.features.current_delay_minutes for e in examples])
    predicted = forecast(booster, examples)
    return {"baseline": metrics(actual, current), "xgboost": metrics(actual, predicted)}


def write_plot(result: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    x = np.arange(2)
    for offset, (method, label, color) in zip(
        (-0.18, 0.18),
        (
            ("baseline", "Current-delay carryover", "#64748b"),
            ("xgboost", "XGBoost next station", "#0d9488"),
        ),
    ):
        heights = [result[method][key] for key in ("mae_minutes", "rmse_minutes")]
        bars = ax.bar(x + offset, heights, width=0.34, label=label, color=color)
        ax.bar_label(bars, fmt="%.2f", padding=3)
    ax.set_xticks(x, ["MAE", "RMSE"])
    ax.set_ylabel("Error (minutes; lower is better)")
    ax.set_title("Later synthetic journeys · six trains\nNot measured railway accuracy")
    ax.set_ylim(0, max(result["baseline"].values()) * 1.3)
    ax.legend(loc="upper left")
    fig.savefig(path, dpi=160)
    plt.close(fig)


def train(input_path: Path, output: Path) -> dict:
    raw = (
        gzip.decompress(input_path.read_bytes())
        if input_path.suffix == ".gz"
        else input_path.read_bytes()
    )
    data = json.loads(raw)
    if data.get("provenance", {}).get("kind") != "synthetic":
        raise ValueError("This demo pipeline accepts explicitly synthetic data only")
    examples = examples_from_records(data)
    train_rows, valid_rows, test_rows = chronological_split(examples)
    dtrain = matrix(train_rows)
    dtrain.set_label([e.target - e.features.current_delay_minutes for e in train_rows])
    values = np.array([feature_vector(e.features) for e in train_rows])
    ranges = {
        name: [float(np.nanmin(values[:, i])), float(np.nanmax(values[:, i]))]
        for i, name in enumerate(FEATURE_NAMES)
        if np.isfinite(values[:, i]).any()
    }
    candidates = []
    for depth in (2, 4, 6):
        params = {
            "objective": "reg:squarederror",
            "tree_method": "hist",
            "max_depth": depth,
            "eta": 0.07,
            "seed": 2026,
            "nthread": 1,
            "min_child_weight": 10,
        }
        booster = xgb.train(params, dtrain, num_boost_round=160)
        booster.set_attr(training_ranges=json.dumps(ranges))
        score = evaluate(booster, valid_rows)["xgboost"]["mae_minutes"]
        candidates.append((score, booster, params))
    _, best, params = min(candidates, key=lambda item: item[0])
    result = evaluate(best, test_rows)
    baseline_mae = result["baseline"]["mae_minutes"]
    improvement = 1 - result["xgboost"]["mae_minutes"] / baseline_mae if baseline_mae else 0.0
    passed = (
        improvement >= 0.10
        and result["xgboost"]["rmse_minutes"] < result["baseline"]["rmse_minutes"]
    )
    models, results = output / "models", output / "results"
    models.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    model_path = models / "eta_model.json"
    best.save_model(model_path)
    boundaries = {}
    for name, rows in zip(("train", "validation", "test"), (train_rows, valid_rows, test_rows)):
        boundaries[name] = {
            "rows": len(rows),
            "journeys": len({e.journey_id for e in rows}),
            "first_observation": min(e.features.as_of for e in rows).isoformat(),
            "last_label": max(e.label_at for e in rows).isoformat(),
            "first_journey_start": min(e.journey_started_at for e in rows).isoformat(),
            "last_journey_end": max(e.journey_ended_at for e in rows).isoformat(),
        }
    metadata = {
        "model_version": "synthetic-next-station-v1",
        "feature_version": FEATURE_VERSION,
        "trained_at": datetime.now(UTC).isoformat(),
        "xgboost_version": xgb.__version__,
        "features": FEATURE_NAMES,
        "target": "next_station_delay_minus_current_delay_minutes",
        "prediction": "max(0, current_delay_minutes + raw_model_prediction); "
        "API also floors arrival at as_of; outside training ranges uses baseline",
        "explanation": "exact native TreeSHAP of the residual; bias + contributions = raw residual",
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "network_sha256": hashlib.sha256(DATA_PATH.read_bytes()).hexdigest(),
        "data_sha256": hashlib.sha256(raw).hexdigest(),
        "provenance": data["provenance"],
        "training_ranges": ranges,
        "split": boundaries,
        "parameters": params,
        "rounds": 160,
        "validation_candidates": [
            {"max_depth": p["max_depth"], "mae_minutes": score} for score, _, p in candidates
        ],
        "test_metrics": result,
        "mae_improvement_fraction": improvement,
        "acceptance_passed": passed,
        "acceptance_rule": "Test MAE at least 10% lower and RMSE lower than carryover baseline",
        "excluded_inputs": "Unversioned historical averages and counts (availability unknown)",
        "limitations": "Synthetic independent simulator journeys only. Sampling-correlated rows; "
        "journeys are disjoint across time splits. No evidence of real railway accuracy. "
        "No inference for downstream stations, inferred journey anchors, or unseen congestion. "
        "Test journeys must not be used for subsequent parameter selection.",
    }
    (models / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    report = {
        "overall": result,
        "by_train": {},
        "split": boundaries,
        "acceptance_passed": passed,
        "mae_improvement_fraction": improvement,
    }
    for number in sorted({e.train_number for e in test_rows}):
        report["by_train"][number] = evaluate(
            best, [e for e in test_rows if e.train_number == number]
        )
    (results / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Held-out synthetic evaluation",
        "",
        "No real railway accuracy claim.",
        "",
        "| Model | MAE (min) | RMSE (min) |",
        "|---|---:|---:|",
    ]
    for method, scores in result.items():
        lines.append(f"| {method} | {scores['mae_minutes']:.3f} | {scores['rmse_minutes']:.3f} |")
    lines += [
        "",
        f"MAE improvement: {improvement:.1%}. Acceptance passed: {passed}.",
        "",
        "Model depth selected only on validation. Later complete journeys held out for test.",
        "See metadata.json for split boundaries, checksums, parameters and limitations.",
    ]
    (results / "comparison.md").write_text("\n".join(lines) + "\n")
    write_plot(result, results / "comparison.png")
    print(json.dumps(report, indent=2), flush=True)
    if not passed:
        raise RuntimeError(
            "Evaluation did not meet the predeclared acceptance gate; do not promote"
        )
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("ml/data/synthetic.json.gz"))
    parser.add_argument("--output", type=Path, default=Path("ml"))
    args = parser.parse_args()
    train(args.input, args.output)


if __name__ == "__main__":
    main()
