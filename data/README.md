# Historical network fixture

`rail_network.json` contains six sourced routes, all 91 stopping records and
63 unique stations. Provenance, licenses, immutable source URLs and checksums
are documented in [data_sources.md](../docs/data_sources.md).

Regenerate from the repository root with `python3 scripts/build_dataset.py`.
Do not manually invent or silently correct station/schedule data. Geometry and
telemetry are explicitly synthetic; these are not current operational schedules.
