# ETA experiment lab — SIH26028

Open `/lab` after normal Compose startup. This is a stateless, reproducible
experiment with the reviewed synthetic model, separate from RailRadar and the
simulator. It makes no provider request and writes no observations, incidents,
model weights or configuration. Inference runs on the backend; the UI does not
invent predictions. No training is performed.

## Demonstration

1. Choose **Quiet section**, then **Run experiment**. The carryover baseline
   retains the input delay. The quiet reference and selected scenario agree.
2. Choose **Severe disruption** and run again. Delay, distance and elapsed time
   stay fixed; one synthetic severity-3 event changes the model inputs. Inspect
   the signed TreeSHAP contributions. The model may change only slightly and is
   not constrained to respond monotonically. Do not claim an event caused the
   difference, or that a lower predicted delay means better accuracy.
3. Choose **Unseen congestion**. Three nearby trains exceed the artifact's
   supported range (0–1), so the selected scenario returns the carryover baseline
   with an explicit reason. The quiet reference can still use XGBoost.
4. Review the held-out metrics, journey splits and artifact checksum. The scores
   come from the loaded artifact's metadata, not a hard-coded browser claim or
   a new evaluation performed by the experiment.
5. Download the JSON result: it includes inputs, explanations, source, model
   identity, evaluation evidence, limitations, problem ID and export time.
   Editing inputs clears the prior result and disables export until another run.

This predicts **delay at the next station**, not an absolute arrival timestamp:
there is no real train, timetable or observed arrival in a hypothetical input.
The delay is floored at zero using the same Predictor as serving. The production
API's separate observation-time arrival floor does not apply here. Fixed time
context is Thursday 12:00 IST; the reference removes the event and nearby trains
while keeping other inputs identical. Historical averages remain unknown.
Individual range checks do not guarantee that combinations are in distribution.
No calibrated uncertainty interval is available.

## API

`GET /demo/scenario` (browser proxy: `/api/demo/scenario`) accepts:

| Query | Default | Bounds |
| --- | ---: | --- |
| `current_delay_minutes` | 15 | 0–180, finite |
| `distance_km` | 20 | 0.1–500, finite |
| `elapsed_minutes` | 15 | 0–600, finite |
| `event_severity` | 0 | Integer 0–3; zero means no active event |
| `nearby_trains` | 0 | Integer 0–5 |

Unknown parameters and invalid input return 422 before inference. Each request
performs two bounded model explanations. Responses use `Cache-Control: no-store`.
The response source is always `hypothetical_synthetic`. It includes independent
`baseline_delay_minutes`, `reference`, `scenario`, `inputs`, and `evidence`.
Each prediction has `method`, `predicted_delay_minutes`, `reason`, and optional
`explanation`. Unsupported inputs return `outside_training_domain`; disabled or
failed inference returns `model_unavailable`, both with the independent baseline.
When no reviewed artifact loads, evaluation evidence is null. This endpoint is
public like existing reads and intended for the local prototype; it is not an
operational rail-control API.

Tests cover actual artifact parity, SHAP reconciliation, repeatability, invalid
inputs, model failures, fallback, evidence exports, edited inputs, desktop/mobile
layout and API recovery. Automated experiments never use the RailRadar key.
