# Simulator

Use Python 3.12 and the standard library. Movement uses the same checked-in
`data/rail_network.json` fixture that the backend seeds. Never fetch live
railway feeds or invent station data. Keep event descriptions explicitly synthetic.

The clock runs at real-time speed. Timetable seconds are unwrapped across
midnight in Asia/Kolkata, while telemetry timestamps are timezone-aware UTC.
Keep UUIDs unchanged during HTTP retries. A restarted or completed train gets
a new journey ID. Do not train models here.

Tests live in `backend/tests/test_simulator.py` and run with the backend pytest
suite. Run Ruff using `--config backend/pyproject.toml` from the repository root.
For a release, also run the documented two-minute HTTP-to-PostGIS smoke check.

Station-connector geometries and directional 5 km occupancy blocks are demo
approximations. They are not surveyed track geometry or operational signaling.
