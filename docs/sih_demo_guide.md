# SIH26028: demonstration and validation plan

**Dynamic Forecast of Expected Time of Arrival (ETA) for Coaching Trains**

Problem ID and title were supplied by the team on 4 October 2026. Confirm the
complete problem statement and submission rules in your SIH portal before
submitting; this document does not invent a sponsor mandate or a 2026 scoring
rubric. The [published college SPOC guidelines](https://sih.gov.in/letters/Guidelines-College-SPOC.pdf)
are an older reference for novelty, feasibility, impact and clarity, not a
verified current round's rubric.

## Position the contribution accurately

RailScope combines an explainable next-station forecasting prototype, an
independent baseline, visible failure/fallback behavior, and three consumer views.
RailRadar adds a separate real-report integration. The contribution to demonstrate
is the forecast and its evidence, not simply displaying a third-party train API.
Do not claim these techniques are novel research or that competitor apps lack them.

A concise opening:

> We are building an explainable arrival forecasting prototype. It compares a
> next-station model against carrying the current delay forward, exposes its
> reasoning, and falls back when inputs exceed its supported domain. Today we can
> demonstrate the full software path on simulated journeys and separately query
> real train reports. Real-world accuracy is the next validation milestone.

## Four-minute walkthrough

| Time | Action | What the audience can verify |
| --- | --- | --- |
| 0:00–0:35 | State the passenger/station-planning problem; open `/lab`. | The problem ID and hypothetical-data label. |
| 0:35–1:30 | Run quiet and severe-disruption presets; open explanations. | Actual XGBoost responses, independent baseline, reconciled TreeSHAP. |
| 1:30–2:00 | Run unseen congestion. | Explicit baseline fallback rather than unsupported ML. |
| 2:00–2:35 | Show evaluation evidence and export the experiment. | Chronological journey splits, model identity, synthetic metrics and caveats. |
| 2:35–3:15 | Open `/`, enter a known train and correct origin date. | Provider timestamp, cache/freshness, real route and reported-station distinction. If unavailable, show the honest failure state. |
| 3:15–4:00 | Open `/demo`, station and control views; close with the pilot plan. | Shared simulated ETA, visible source labels, and a concrete path to real validation. |

The lab needs the local backend and artifact but no external provider or database.
Start the full Compose stack for the other screens. Rehearse with Wi-Fi off to
confirm the lab still works; base map tiles need network, while map overlays can
remain visible. Never relabel a saved screenshot or synthetic fixture as live.
Keep a local screen recording as a presentation backup, labelled with capture date.

## Claims you can defend

| Claim | Evidence / limit |
| --- | --- |
| Model beats the baseline in the bundled experiment | `ml/results/metrics.json`: MAE 33.941 → 5.759 minutes on 24 held-out **synthetic** journeys. Not real railway accuracy. |
| Model explanation is consistent | Native TreeSHAP reconciliation and serving parity tests. Attribution is not causation. |
| Out-of-domain fallback exists | Lab congestion preset and artifact tests. Range checks cannot catch all distribution shifts. |
| Real reports are integrated | RailRadar `/live` lookup with upstream timestamp and provider geometry. It is not a GPS feed or the source of our model's training labels. |
| Application works end to end | Compose, CI, API/WebSocket verifier and real-stack browser checks. National scale is not measured. |

Do not claim “83% accurate”: the ~83% figure is a reduction in synthetic MAE.
Do not invent passenger time saved, deployment savings, provider reliability,
confidence bands, railway partnerships, or approved operational use.

## Next validation milestone: a prospective shadow pilot

This plan is not an implemented collector or an active scheduled task.

1. Confirm allowed retention and use of provider reports. Pick a small set of
   journeys within the free quota; one cached lookup is not another observation.
2. Save immutable prediction-time snapshots with train number, origin date,
   provider report timestamp, fetch timestamp, station sequence, input values and
   model version. Keep these separate from synthetic telemetry and training data.
3. Establish actual arrival labels independently. RailRadar `actualArrival` can
   contain estimates; an upcoming station's value must never become ground truth.
   Require documented observed/completed evidence and manual audits of a sample.
4. Freeze an evaluation protocol before collecting the test period: group by
   complete journey, keep chronology, exclude stale/unknown observations, prevent
   post-arrival predictions, and report coverage plus MAE/RMSE by forecast horizon.
5. Compare current-delay carryover, provider estimates, and the candidate model
   on the same eligible observations. Report per-journey errors and journey-level
   uncertainty, not confidence intervals treating correlated rows as independent.
6. Promote a real-data model only after sufficient labelled journeys and a
   reviewed evaluation. Keep shadow predictions out of operational decisions.

The immediate gaps are trustworthy arrival labels, real-world evaluation and
user feedback. Interview passengers and station staff about which forecast
horizons and stale-data warnings help them; record consented feedback instead
of claiming unmeasured adoption. Test workload/latency separately before scale claims.

## Submission checklist

Team members and roles; verified full problem statement; slide format/deadline
from the current portal; a four-minute rehearsed demo; source/data attribution;
model card and evaluation evidence; setup instructions; labelled offline backup;
a clear account of what is implemented and what is still a pilot proposal.
