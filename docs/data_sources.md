# Data provenance and limitations

The checked-in `data/rail_network.json` is an **archived demonstration dataset**,
not the 2026 operating timetable. Station names/codes and train-name abbreviations
are preserved from the historical source. Do not use it for travel planning.
No live NTES scraping or fabricated station names were used.

## Timetable

- Publisher: Ministry of Railways, Government of India, via the
  [Indian Railways Train Time Table catalog](https://www.data.gov.in/catalog/indian-railways-train-time-table).
- Historical CSV: `isl_wise_train_detail_03082015_v1.csv`, a 2015 snapshot.
- The original catalog identifies the Ministry, NDSAP release, and
  [Government Open Data License – India](https://www.data.gov.in/government-open-data-license-india).
  Attribution is retained here; no government endorsement is implied.
- Downloaded from the public archival mirror in
  [napsternxg/ipython-notebooks at f327874fcf7b99c19c82919ad1cdba01660d2ef1](https://github.com/napsternxg/ipython-notebooks/blob/f327874fcf7b99c19c82919ad1cdba01660d2ef1/data/isl_wise_train_detail_03082015_v1.csv).
  The repository's IRCTC Data Hack notebook identifies data.gov.in as its source.
- [Exact CSV bytes](https://raw.githubusercontent.com/napsternxg/ipython-notebooks/f327874fcf7b99c19c82919ad1cdba01660d2ef1/data/isl_wise_train_detail_03082015_v1.csv).
- SHA-256: `2549b40343f509454dd2e84f0375a5d3d200593b3c01e91ea217baae800b5ee8`.

The fixture contains every source stop for the selected routes (91 stops across
six trains), with source arrival/departure times and cumulative rail distances.
Leading quote characters and surrounding whitespace are stripped. Sequence
numbers become zero-based. The source's `00:00:00` at the origin arrival and
terminal departure is converted to null **only at those endpoints**; genuine
intermediate midnight times remain valid. Overnight day offsets are inferred by
walking arrival then departure times monotonically and adding 24 hours at each
clock rollover. Offsets are seconds since day-one midnight in Asia/Kolkata.

| Train | Source name | Route | Source distance | Stops |
| --- | --- | --- | ---: | ---: |
| 12301 | KOLKATA RAJDHNI | HWH → NDLS | 1447 km | 11 |
| 12621 | TAMIL NADU EXP | MAS → NDLS | 2182 km | 12 |
| 12622 | TAMIL NADU EXP | NDLS → MAS | 2182 km | 11 |
| 12627 | KARNATAKA EXP | SBC → NDLS | 2406 km | 36 |
| 12952 | MUMBAI RAJDHANI | NDLS → BCT | 1384 km | 7 |
| 12953 | AUG KR RAJ EXP | BCT → NZM | 1377 km | 14 |

Selection requires complete station coordinates, increasing distances, positive
running times and segment-average speeds no greater than 130 km/h. Some other
candidate routes were excluded because their archived entries failed that speed
check. Values for the selected routes were not silently corrected or invented.
The archival source can still contain errors; these checks establish internal
plausibility, not current timetable authority. Source distances are rounded km.

## Station coordinates and zones

- Publisher: [DataMeet / Indian Railways Data](https://github.com/datameet/railways),
  credited to its contributors Sanjay and Sajjad.
- Source revision: `e0c538a1e41ae5eace454d2818902e1065608e16`.
- [Exact stations GeoJSON](https://raw.githubusercontent.com/datameet/railways/e0c538a1e41ae5eace454d2818902e1065608e16/stations.json).
- SHA-256: `9bd5e1da3a859e5359a95f40b6009aa468efb177da4faac57ffdcd7daeb4df18`.
- License: **CC0**, as stated in the
  [source README](https://github.com/datameet/railways/blob/e0c538a1e41ae5eace454d2818902e1065608e16/README.md).

The 63 selected stations join on exact historical station code. Their coordinate
order is converted from GeoJSON `[longitude, latitude]` to explicit lon/lat
fields, while PostGIS POINT uses longitude first with SRID 4326. Station names
come from the timetable and zones/coordinates from DataMeet. These independently
published snapshots are historical and may differ from today's station metadata.

## Geometry and synthetic observations

There is no surveyed track or actual signaling dataset in this fixture.
Each route's PostGIS LINESTRING connects its stopping stations in order; the
simulator interpolates along those **schematic connectors**. Such a line may
cross terrain where no tracks exist. `ST_Length(geom::geography)` gives metres
along this schematic geometry; it must not replace source timetable kilometres.
Spatial indexes support future geographic queries, but exact rail routing needs
an independently sourced track network in a later enhancement.

Directional 5 km occupancy blocks are synthetic. They apply only to identical
ordered adjacent-station pairs within one simulator process. They do not model
actual signal positions, opposing traffic, junction conflicts, train length,
acceleration, braking or all overlapping track sections. This is a demo
mechanism, not a railway safety simulator.

All positions and events carry `source="simulator"`. Historical delay averages
are deliberately **not seeded**: no actual delay observations were sourced.
The historical_delays schema is ready for future evidence-based aggregation.

## Reproduce

From the repository root with Python 3.12 and internet access:

```sh
python3 scripts/build_dataset.py
```

The extractor verifies both upstream SHA-256 hashes before writing the fixture.
Use `--cache /path/to/source-directory` to reuse the two original files named
`timetable.csv` and `stations.json`; the same checksums are still enforced.
Fixture regeneration is deterministic. Tests check routes, day rollovers,
coordinates, source distances and plausible segment speeds. Runtime startup
uses only the checked-in JSON, not upstream downloads.
