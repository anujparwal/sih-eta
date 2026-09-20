"""Recheck recorded test metrics against the exact generated input, without training."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from app.inference import DEFAULT_MODEL_DIR, Predictor
from ml.dataset import chronological_split, examples_from_records
from ml.train import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("ml/data/synthetic.json.gz"))
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    args = parser.parse_args()
    predictor = Predictor(args.model_dir)
    raw = args.input.read_bytes()
    if args.input.suffix == ".gz":
        raw = gzip.decompress(raw)
    if hashlib.sha256(raw).hexdigest() != predictor.metadata["data_sha256"]:
        raise ValueError("Input differs from reviewed evaluation data")
    _, _, test_rows = chronological_split(examples_from_records(json.loads(raw)))
    result = evaluate(predictor.booster, test_rows)
    for method, scores in result.items():
        for metric, value in scores.items():
            expected = predictor.metadata["test_metrics"][method][metric]
            if abs(value - expected) > 1e-6:
                raise ValueError("Replayed evaluation differs from recorded metrics")
    print(json.dumps({"replayed_test_rows": len(test_rows), "metrics": result}, indent=2))


if __name__ == "__main__":
    main()
