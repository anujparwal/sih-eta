import math

from simulator.engine import locate


def test_curated_network_has_six_complete_plausible_historical_routes(dataset):
    stations = {station["code"]: station for station in dataset["stations"]}
    assert len(stations) == len(dataset["stations"]) == 63
    assert len({route["train_number"] for route in dataset["routes"]}) == 6
    assert dataset["schedule_timezone"] == "Asia/Kolkata"
    for station in stations.values():
        assert 6 < station["lat"] < 38
        assert 68 < station["lon"] < 98
        assert station["name"]
    for route in dataset["routes"]:
        stops = route["stops"]
        assert [s["sequence"] for s in stops] == list(range(len(stops)))
        assert stops[0]["arrival_seconds"] is None
        assert stops[-1]["departure_seconds"] is None
        assert stops[0]["distance_km"] == 0
        assert stops[-1]["distance_km"] == route["total_distance_km"]
        assert len({s["station_code"] for s in stops}) == len(stops)
        for origin, destination in zip(stops, stops[1:]):
            distance = destination["distance_km"] - origin["distance_km"]
            duration = destination["arrival_seconds"] - origin["departure_seconds"]
            assert distance > 0 and duration > 0
            assert 0 < distance * 3600 / duration <= 130
            if destination["departure_seconds"] is not None:
                assert destination["departure_seconds"] >= destination["arrival_seconds"]
            a, b = stations[origin["station_code"]], stations[destination["station_code"]]
            lat_a, lat_b = math.radians(a["lat"]), math.radians(b["lat"])
            angle = math.sin((lat_b - lat_a) / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * (
                math.sin(math.radians(b["lon"] - a["lon"]) / 2) ** 2
            )
            geodesic = 6371 * 2 * math.asin(math.sqrt(angle))
            assert geodesic <= distance * 1.1 + 1


def test_multiday_schedule_is_unwrapped_in_ist(dataset):
    route = next(r for r in dataset["routes"] if r["train_number"] == "12627")
    assert route["stops"][0]["departure_seconds"] == 19 * 3600 + 20 * 60
    assert route["stops"][-1]["arrival_seconds"] == 2 * 86400 + 10 * 3600 + 30 * 60
    stations = {s["code"]: s for s in dataset["stations"]}
    endpoint = locate(route, stations, 39 * 3600 + 10 * 60)
    assert endpoint.last_station == "NDLS" and endpoint.next_station is None
    assert endpoint.distance_km == 2406
