import random
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError

import pytest

from simulator.engine import Disruption, Fleet, Train, locate
from simulator.simulate import post

START = datetime(2026, 1, 1, tzinfo=UTC)
STATIONS = {
    "A": {"lat": 20.0, "lon": 77.0},
    "B": {"lat": 20.01, "lon": 77.01},
    "C": {"lat": 20.02, "lon": 77.02},
}
ROUTE = {
    "train_number": "10001",
    "stops": [
        {"station_code": "A", "arrival_seconds": None, "departure_seconds": 0, "distance_km": 0},
        {"station_code": "B", "arrival_seconds": 60, "departure_seconds": 120, "distance_km": 1},
        {"station_code": "C", "arrival_seconds": 180, "departure_seconds": None, "distance_km": 2},
    ],
}


def train():
    result = Train(ROUTE, STATIONS, START, random.Random(42))
    result.next_event_at = float("inf")
    return result


def test_interpolation_and_scheduled_dwell():
    halfway = locate(ROUTE, STATIONS, 30)
    assert halfway.distance_km == 0.5
    assert halfway.lat == pytest.approx(20.005)
    assert halfway.lon == pytest.approx(77.005)
    assert halfway.speed_kmh == 60
    dwell = locate(ROUTE, STATIONS, 90)
    assert dwell.distance_km == 1 and dwell.speed_kmh == 0
    assert (dwell.last_station, dwell.next_station) == ("B", "C")
    vehicle = train()
    for _ in range(90):
        vehicle.advance(1, {})
    assert vehicle.snapshot()["delay_minutes"] == 0


def test_unscheduled_stop_accumulates_delay_and_resumes():
    vehicle = train()
    vehicle.active = Disruption("unscheduled_stop", 2, 0, 60)
    for _ in range(60):
        vehicle.advance(1, {})
    snapshot = vehicle.snapshot()
    assert snapshot["distance_km"] == 0
    assert snapshot["delay_minutes"] == 1
    assert snapshot["current_speed_kmh"] == 0
    vehicle.advance(1, {})
    assert vehicle.location.distance_km > 0
    assert vehicle.snapshot()["delay_minutes"] == 1


def test_speed_restriction_reduces_distance_and_creates_delay():
    vehicle = train()
    vehicle.active = Disruption("speed_restriction", 3, 0, 60)
    for _ in range(60):
        vehicle.advance(1, {})
    assert vehicle.location.distance_km == pytest.approx(0.4)
    assert vehicle.speed == pytest.approx(24)
    assert vehicle.snapshot()["delay_minutes"] == pytest.approx(0.6)


def test_occupied_synthetic_block_prevents_movement():
    vehicle = train()
    reservations = {("A", "B", 0): "another-journey"}
    vehicle.advance(1, reservations)
    assert vehicle.clock == 0 and vehicle.speed == 0
    assert reservations[("A", "B", 0)] == "another-journey"
    reservations.clear()
    vehicle.advance(1, reservations)
    assert vehicle.clock == 1 and reservations[("A", "B", 0)] == vehicle.journey_id


def test_terminal_sample_precedes_a_new_journey():
    dataset = {"routes": [ROUTE], "stations": [{"code": c, **s} for c, s in STATIONS.items()]}
    fleet = Fleet(dataset, START, seed=42)
    fleet.trains[0].next_event_at = float("inf")
    old_id = fleet.trains[0].journey_id
    fleet.advance(190)
    terminal = fleet.trains[0].snapshot()
    assert terminal["journey_id"] == old_id
    assert terminal["next_station"] is None and terminal["distance_km"] == 2
    assert terminal["current_speed_kmh"] == 0
    fleet.advance(1)
    assert fleet.trains[0].journey_id != old_id
    assert fleet.trains[0].location.last_station == "A"


def test_two_minutes_generates_moving_trails_and_events_for_six_trains(dataset):
    fleet = Fleet(dataset, START, seed=42, event_every=30)
    twin = Fleet(dataset, START, seed=42, event_every=30)
    history = [[] for _ in fleet.trains]
    event_count = 0
    for _ in range(24):
        event_count += len(fleet.advance(5))
        twin.advance(5)
        for index, vehicle in enumerate(fleet.trains):
            snapshot = vehicle.snapshot()
            history[index].append(snapshot)
            assert snapshot["distance_km"] == twin.trains[index].snapshot()["distance_km"]
            assert 0 <= snapshot["current_speed_kmh"] <= 130
    assert event_count >= 1
    for trail in history:
        assert trail[-1]["distance_km"] > trail[0]["distance_km"]
        assert all(a["distance_km"] <= b["distance_km"] for a, b in zip(trail, trail[1:]))
        assert all(a["timestamp"] < b["timestamp"] for a, b in zip(trail, trail[1:]))


def test_retry_preserves_the_exact_request_body(monkeypatch):
    requests = []

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def send(request, **kwargs):
        requests.append(request)
        if len(requests) == 1:
            raise URLError("temporarily offline")
        return Response()

    monkeypatch.setattr("simulator.simulate.urlopen", send)
    monkeypatch.setattr("simulator.simulate.time.sleep", lambda _: None)
    post("http://test", "/ingest/position", {"id": "saved-id"})
    assert len(requests) == 2 and requests[0].data == requests[1].data


def test_invalid_payload_is_not_retried(monkeypatch):
    import io

    attempts = []

    def send(request, **kwargs):
        attempts.append(request)
        raise HTTPError(request.full_url, 422, "Invalid", {}, io.BytesIO(b"invalid"))

    monkeypatch.setattr("simulator.simulate.urlopen", send)
    with pytest.raises(RuntimeError, match="422"):
        post("http://test", "/ingest/event", {})
    assert len(attempts) == 1
