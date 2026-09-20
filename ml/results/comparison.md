# Held-out synthetic evaluation

No real railway accuracy claim.

| Model | MAE (min) | RMSE (min) |
|---|---:|---:|
| baseline | 33.941 | 45.098 |
| xgboost | 5.759 | 8.013 |

MAE improvement: 83.0%. Acceptance passed: True.

Model depth selected only on validation. Later complete journeys held out for test.
See metadata.json for split boundaries, checksums, parameters and limitations.
