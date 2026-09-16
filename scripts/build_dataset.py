"""Rebuild the six-train historical fixture from checksum-pinned public sources."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

SOURCES = {
    "timetable.csv": {
        "url": "https://raw.githubusercontent.com/napsternxg/ipython-notebooks/"
        "f327874fcf7b99c19c82919ad1cdba01660d2ef1/data/isl_wise_train_detail_03082015_v1.csv",
        "sha256": "2549b40343f509454dd2e84f0375a5d3d200593b3c01e91ea217baae800b5ee8",
    },
    "stations.json": {
        "url": "https://raw.githubusercontent.com/datameet/railways/"
        "e0c538a1e41ae5eace454d2818902e1065608e16/stations.json",
        "sha256": "9bd5e1da3a859e5359a95f40b6009aa468efb177da4faac57ffdcd7daeb4df18",
    },
}
TRAIN_NUMBERS = ("12301", "12621", "12622", "12627", "12952", "12953")


def read_source(name: str, cache: Path | None) -> bytes:
    source = SOURCES[name]
    if cache is not None and (cache / name).exists():
        content = (cache / name).read_bytes()
    else:
        with urlopen(source["url"], timeout=60) as response:
            content = response.read()
    if hashlib.sha256(content).hexdigest() != source["sha256"]:
        raise ValueError(f"Source checksum mismatch: {name}")
    return content


def seconds(value: str, previous: int) -> int:
    hour, minute, second = map(int, value.strip("' ").split(":"))
    result = hour * 3600 + minute * 60 + second
    while result < previous:
        result += 86400
    return result


def build(cache: Path | None = None) -> dict:
    rows = list(csv.DictReader(io.StringIO(read_source("timetable.csv", cache).decode())))
    features = json.loads(read_source("stations.json", cache))["features"]
    station_lookup = {f["properties"]["code"]: f for f in features}
    stations, routes = {}, []
    for number in TRAIN_NUMBERS:
        rows_for_train = sorted(
            (r for r in rows if r["Train No."].strip("' ") == number),
            key=lambda row: int(row["islno"]),
        )
        if len(rows_for_train) < 2:
            raise ValueError(f"Missing route {number}")
        stops, previous = [], 0
        for index, row in enumerate(rows_for_train):
            code = row["station Code"].strip()
            feature = station_lookup[code]
            lon, lat = feature["geometry"]["coordinates"]
            stations[code] = {
                "code": code,
                "name": row["Station Name"].strip(),
                "zone": feature["properties"]["zone"],
                "lat": lat,
                "lon": lon,
            }
            arrival = None if index == 0 else seconds(row["Arrival time"], previous)
            departure = (
                None
                if index == len(rows_for_train) - 1
                else seconds(row["Departure time"], arrival if arrival is not None else 0)
            )
            previous = departure if departure is not None else arrival
            stops.append(
                {
                    "sequence": index,
                    "station_code": code,
                    "arrival_seconds": arrival,
                    "departure_seconds": departure,
                    "distance_km": float(row["Distance"]),
                }
            )
        routes.append(
            {
                "train_number": number,
                "train_name": rows_for_train[0]["train Name"].strip(),
                "total_distance_km": stops[-1]["distance_km"],
                "stops": stops,
            }
        )
    return {
        "dataset_version": "ogd-2015-six-trains-v1",
        "schedule_timezone": "Asia/Kolkata",
        "geometry_kind": "schematic_station_connectors",
        "sources": SOURCES,
        "stations": sorted(stations.values(), key=lambda station: station["code"]),
        "routes": routes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "rail_network.json",
    )
    args = parser.parse_args()
    dataset = build(args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(dataset['routes'])} routes and {len(dataset['stations'])} stations")
