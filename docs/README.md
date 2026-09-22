# RailScope — Dynamic ETA Forecast for Coaching Trains

RailScope is an SIH 2026 project prototype for updating train arrival estimates
as observed delays change. It gives passengers, station displays and a control
room access to the same ETA calculation, with a visible baseline and model
explanations. The implemented demo runs **six simulated trains on real historical
Indian routes**, covering 63 stations. It does not connect to live railway feeds.

## What the prototype demonstrates

A Python simulator sends positions and disruption events to a FastAPI backend.
PostgreSQL/PostGIS stores the observations and sourced route geometry. Shared
features feed an XGBoost next-station model and a current-delay carryover
baseline. Redis notifications drive live updates, while one Next.js app presents
passenger, station and control views. The [architecture diagram and component
summary](architecture.md#system-overview) can be used in the submission or pitch.

| View | Open after startup | What to show |
| --- | --- | --- |
| Passenger | [Train 12301](http://localhost:3000/?train=12301) | Search, schematic route map, observed position, next-station ML versus baseline, TreeSHAP explanation |
| Station display | [New Delhi board](http://localhost:3000/station/NDLS) | Ordered arrivals, IST date/time, prediction method and freshness |
| Control room | [Fleet dashboard](http://localhost:3000/control) | Six-train state, delay filters/sorting, route map, journey history and events |

The station board shows ML only when that station is the train's **next** stop;
other upcoming stations retain the baseline. Platform assignments are unavailable
and displayed as placeholders.

## Run locally from a fresh clone

Install Git and Docker Engine/Desktop with Compose v2, and start Docker. Use a
terminal with a POSIX shell (Linux/macOS, or WSL on Windows). Ports 3000 and 8000
must be free. Images and packages need internet access on the first build; host
Python, Node.js, railway credentials and model training are not required.

```sh
git clone https://github.com/anujparwal/sih-eta.git
cd sih-eta
cp .env.example .env
docker compose up --build -d --wait
docker compose ps
```

Run these commands from the repository root, not `docs/`. On an existing
checkout, keep your existing `.env`; copy the example only when it is absent.
If your Compose executable is named `docker-compose`, substitute that spelling.
PostgreSQL, Redis, the backend and frontend should report healthy, and the
continuous simulator should be running. The API migrates and seeds automatically;
all six trains then become active within a few sampling intervals.

Open the three links above and [interactive API docs](http://localhost:8000/docs).
For a terminal check (requires curl):

```sh
curl --fail http://localhost:8000/ready
curl --fail 'http://localhost:8000/trains?active_only=true'
```

Readiness should return
`{"status":"ok","dependencies":{"postgres":"ok","redis":"ok"}}`.
The train response should contain six entries with `status: active`. Allow about
five seconds for each new telemetry sample. First downloads/builds may take more
than two minutes; Phase 9 measured startup at 31 seconds with prebuilt images.
The archived network fixture and reviewed model are bundled in the repository.

If startup fails, run `docker compose logs --tail=100`. If a port is occupied,
edit BACKEND_PORT/FRONTEND_PORT in `.env`, align NEXT_PUBLIC_API_BASE_URL with the
backend's browser-accessible URL, then run the build/start command again and use
the new ports. A healthy but empty or stale dashboard warrants checking
`docker compose logs --tail=100 simulator`. After laptop sleep or a system clock
change, use `docker compose restart simulator` to anchor new journeys to the
current time. Run only one simulator per database.
More configuration and hosting steps are in [deployment.md](deployment.md).

To stop and later resume the local demo:

```sh
docker compose down
docker compose up -d --wait
```

Named volumes preserve observations. Adding `-v` to `down` deletes them. To pause
only telemetry, use `docker compose stop simulator`; resume with
`docker compose start simulator`. Restarting the simulator creates fresh journey
IDs and leaves earlier history intact. Existing volume credentials do not change
when `.env` passwords are edited.

## How the model works

The independent baseline carries the current observed delay forward to each
upcoming scheduled arrival. The timetable is anchored to the simulated journey's
start, including overnight offsets; it is not today's operating timetable.

The shipped `synthetic-next-station-v1` XGBoost model predicts a residual: the
change from current delay to delay at the next station. Its nine inputs cover
observed time since the last station, remaining timetable distance, current
delay, IST weekday/hour, active event count/severity and nearby-train congestion.
Training and serving share the feature arithmetic. Features use only evidence
available at the observation time; missing station timing stays missing.
Unversioned historical delay averages are excluded from the model.

The predicted residual is added to current delay, with a zero-delay floor and
an arrival floor at the observation time. Exact TreeSHAP contributions explain
the model residual; the response separately identifies clipping adjustments.
These are model attributions, not proof that an incident caused a delay.
Missing/invalid models, unsupported inputs or inferred journey starts fall back
to the labeled baseline. Later stations always use the baseline.

The reviewed JSON artifact is loaded at startup. Predictions update as new
telemetry arrives; model weights do **not** continuously retrain. Training and
artifact promotion are separate offline steps. See the [model card](../ml/README.md)
for features, leakage controls, artifact checksums and reproduction commands.

## Measured improvement on synthetic data

| Held-out prediction | MAE, minutes | RMSE, minutes |
| --- | ---: | ---: |
| Current-delay carryover baseline | 33.941 | 45.098 |
| XGBoost with serving fallbacks and clipping | 5.759 | 8.013 |

MAE (mean absolute error) fell **83.0%**; RMSE (root mean square error) also
improved. The result covers **24 held-out synthetic journeys / 26,146 feature
rows**, after 66 training and 18 validation journeys. Complete journeys were
split chronologically; model depth was selected on validation data. Correlated
rows within a journey are not independent trials.

These figures describe simulator-generated delays, **not measured accuracy on
real railway services**. The model can learn this simulator's dynamics; deployment
on operational data needs new evaluation. Evidence: [machine-readable metrics](../ml/results/metrics.json),
[evaluation table](../ml/results/comparison.md) and [comparison chart](../ml/results/comparison.png).

## A short demonstration

1. Open train 12301 after startup. Point out the simulated-data label, advancing
   observation time and route position. Compare the next-station prediction with
   its carryover baseline and explain a TreeSHAP contribution.
2. Open the station board and select the next station shown for that train
   (DKAE on a fresh 12301 journey). Compare the arrival estimate and IST date.
3. Open the control room, sort/filter delays, and open a train's recorded history
   and events. Incidents occur randomly, so do not promise an event at a fixed
   moment. The [two-minute acceptance sequence](../README.md#two-minute-acceptance-check)
   increases event frequency for a repeatable technical demonstration.
4. Show the evaluation chart with its synthetic-data caveat. A short live demo
   illustrates the interface and transport; it does not reproduce the training
   experiment or establish real-world prediction accuracy.

## API, checks and submission scope

The [API contract](api_contract.md) documents all HTTP/WS endpoints, schemas,
features, timing rules, errors and retry behavior. The [test guide](testing.md)
and [phase acceptance map](phase_acceptance.md) link each implemented capability
to evidence. The latest Phase 9 acceptance passed 175 backend/ML tests, 76
mocked desktop/mobile browser tests and one real-stack browser test. CI repeats
these checks, builds and the two-minute telemetry smoke on every push and PR.

| Evidence or capability | Current boundary |
| --- | --- |
| Routes and stations | Sourced historical timetable and coordinates: six routes, 63 stations, 91 route stops. Not the current operating schedule. Attribution and checksums are in [data sources](data_sources.md). |
| Positions and incidents | Generated telemetry stands in for live GPS/signal feeds; this repository has no operational railway feed integration. Weather events are simulated. |
| Maps and congestion | Straight station connectors and simplified directional blocks, not surveyed tracks, real signal locations or operational safety logic. |
| Predictions | Next-station ML only, assessed on synthetic data. Out-of-domain checks cannot detect every distribution shift. No automatic online learning or LSTM model. |
| Missing evidence | Unknown history stays null; platforms have no assignments; observations become stale after 30 seconds. |
| Delivery and access | Redis pub/sub has no durable replay. Reconciliation and cache expiry repair missed current-state updates. Optional ingestion Bearer key; reads/WS remain public, with no user roles. |
| Deployment | Local Compose verified; Render/Vercel configuration and manual instructions prepared. Cloud availability, scale and operational use are not validated. |

This documentation is the software submission overview. For the final submission,
add your team details, official problem ID, pitch deck and hosted demo URL.
