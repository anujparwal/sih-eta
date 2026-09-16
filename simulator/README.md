# Synthetic telemetry simulator

Run from the repository root with Python 3.12 (standard library only):

```sh
python3 simulator/simulate.py --api-url http://localhost:8000 --duration 120
```

The backend must already be migrated and seeded. See the root README for the
Docker Compose `simulation` profile and repeatable two-minute acceptance check.
Omit `--duration` for continuous simulation. `--interval` defaults to five real
seconds; `--seed 42` reproduces the movement/event random sequence with the same
tick sequence. Sample/journey/event UUIDs are intentionally fresh each run.
There is no accelerated simulation clock and timestamps include UTC offsets.

All six trains start at their origin. Running time and station dwell come from
the archived timetable. Event types are speed_restriction, unscheduled_stop,
congestion and weather. Events last 60–180 seconds; severity 1–3 reduces planned
progress by 20–60% for restrictions/weather, or stops it for halts/congestion.
Delay is actual elapsed time minus planned timetable progress. The mean wait
between events is `--event-every` seconds (default 180, minimum wait 20).
An expired event is cleared before the next event is scheduled.

A train reaches the final station with zero speed; its terminal sample is sent
before it receives a new journey ID at the next tick. Restarting the process
also begins fresh journeys. Old trails remain queryable by journey_id. Network
and HTTP 429/5xx failures retry the exact request body up to five times with
bounded backoff. Permanent 4xx errors and exhausted retries stop the process
with an error instead of silently losing or duplicating samples.

Movement is broken into steps no longer than one second. Directional synthetic
5 km blocks prevent entry into an occupied block for identical adjacent-station
pairs in this process. Run only one simulator process. Blocks do not model real
signals or all shared physical tracks. Geometry is a straight connector between
stops, not a surveyed rail alignment. Speed changes have no acceleration model.
See [data sources](../docs/data_sources.md) for the explicit approximations.

Unit tests for movement, dwell, delay events, block occupancy, retries and
journey completion are in backend/tests/test_simulator.py and run with pytest.
