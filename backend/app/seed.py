"""Idempotently seed the bundled historical timetable; never fabricate delay history."""

import json
from pathlib import Path

from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Route, RouteStop, Station

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "rail_network.json"
if not DATA_PATH.exists():
    DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "rail_network.json"


def load_dataset() -> dict:
    return json.loads(DATA_PATH.read_text())


def seed_network(session: Session) -> None:
    dataset = load_dataset()
    stations = {station["code"]: station for station in dataset["stations"]}
    for station in stations.values():
        session.execute(
            insert(Station)
            .values(
                **station, geom=WKTElement(f"POINT({station['lon']} {station['lat']})", srid=4326)
            )
            .on_conflict_do_nothing(index_elements=[Station.code])
        )
    for route in dataset["routes"]:
        points = [stations[stop["station_code"]] for stop in route["stops"]]
        line = "LINESTRING(" + ",".join(f"{p['lon']} {p['lat']}" for p in points) + ")"
        session.execute(
            insert(Route)
            .values(
                train_number=route["train_number"],
                train_name=route["train_name"],
                total_distance_km=route["total_distance_km"],
                dataset_version=dataset["dataset_version"],
                geometry_kind=dataset["geometry_kind"],
                geom=WKTElement(line, srid=4326),
            )
            .on_conflict_do_nothing(index_elements=[Route.train_number])
        )
        record = session.scalar(select(Route).where(Route.train_number == route["train_number"]))
        if record.dataset_version != dataset["dataset_version"]:
            raise ValueError("Existing route uses another dataset version; migrate explicitly")
        for stop in route["stops"]:
            session.execute(
                insert(RouteStop)
                .values(
                    route_id=record.id,
                    **stop,
                )
                .on_conflict_do_nothing(index_elements=[RouteStop.route_id, RouteStop.sequence])
            )


if __name__ == "__main__":
    with Session(get_engine()) as session, session.begin():
        seed_network(session)
    print("Historical network seeded: 6 routes; no synthetic delay history inserted.")
