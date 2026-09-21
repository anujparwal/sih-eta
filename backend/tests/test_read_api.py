from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import read_api
from app.eta import build_eta, get_route, route_stops
from app.features import compute_features, latest_positions
from app.main import app
from app.models import HistoricalDelay, LivePosition
from simulator.engine import Fleet

NOW = datetime(2026, 9, 17, 18, 40, tzinfo=UTC)


@pytest.fixture
def clock():
    value = [NOW]
    app.dependency_overrides[read_api.utc_now] = lambda: value[0]
    yield value
    app.dependency_overrides.pop(read_api.utc_now, None)


@pytest.fixture
def send_train(dataset, request_api, db):
    def send(index=0, elapsed=600, nominal=300, end=NOW, **changes):
        fleet = Fleet(dataset, end - timedelta(seconds=elapsed), seed=42)
        train = fleet.trains[index]
        train.elapsed, train.clock = elapsed, nominal
        payload = train.snapshot() | changes
        response = request_api("POST", "/ingest/position", payload)
        assert response.status_code == 201, response.text
        return payload

    return send


def get(request_api, path):
    response = request_api("GET", path, None)
    assert response.status_code == 200, response.text
    return response.json()


def test_seeded_network_without_telemetry_is_honest(db, request_api, clock):
    rows = get(request_api, "/trains")["trains"]
    assert len(rows) == 6 and all(r["status"] == "no_data" for r in rows)
    assert get(request_api, "/trains?active_only=true")["trains"] == []
    eta = get(request_api, "/trains/12301/eta")
    assert eta["stations"] == [] and eta["features"] is None and eta["as_of"] is None
    assert eta["timing_basis"] == "unavailable"
    assert get(request_api, "/trains/12301/history")["positions"] == []
    assert get(request_api, "/stations/NDLS/arrivals")["arrivals"] == []
    fleet = get(request_api, "/control/fleet-status")
    assert fleet["no_data_trains"] == 6 and fleet["mean_active_delay_minutes"] is None


def test_baseline_hand_calculated_and_board_matches(db, request_api, clock, send_train):
    payload = send_train()  # Start 18:30, nominal five minutes, observed ten: delay five.
    eta = get(request_api, "/trains/12301/eta")
    assert eta["timing_basis"] == "provided" and eta["journey_id"] == payload["journey_id"]
    assert eta["current_delay_minutes"] == 5
    first = eta["stations"][0]  # HWH -> DKAE: 20 scheduled minutes.
    assert first["station_code"] == "DKAE"
    assert datetime.fromisoformat(first["scheduled_arrival"]) == NOW + timedelta(minutes=10)
    assert datetime.fromisoformat(first["baseline_eta"]) == NOW + timedelta(minutes=15)
    assert first["prediction_method"] == "xgboost_next_station"
    assert first["model_version"] == "synthetic-next-station-v1"
    assert first["eta_baseline_minutes"] == 15
    assert first["eta_ml_minutes"] is not None
    assert first["eta"] == first["ml_eta"]
    assert eta["eta_ml_minutes"] == first["eta_ml_minutes"]
    assert first["explanation"]["method"] == "tree_shap"
    assert len(eta["stations"]) == 10
    board = get(request_api, "/stations/DKAE/arrivals")["arrivals"]
    assert len(board) == 1
    assert board[0]["baseline_eta"] == first["baseline_eta"]
    assert get(request_api, "/stations/HWH/arrivals")["arrivals"] == []
    assert eta["features"]["minutes_since_last_station"] == 10
    assert eta["features"]["distance_remaining_next_station_km"] == 11.25  # 15 - 3.75


def test_stale_boundary_and_fleet_denominators(db, request_api, clock, send_train):
    send_train()  # active, five-minute delay
    send_train(index=1, elapsed=600, nominal=0, end=NOW - timedelta(seconds=31))  # stale
    send_train(index=2, elapsed=600, nominal=600)  # active, on time
    clock[0] = NOW + timedelta(seconds=30)
    fleet = get(request_api, "/control/fleet-status")
    assert (fleet["active_trains"], fleet["stale_trains"], fleet["no_data_trains"]) == (2, 1, 3)
    assert fleet["delayed_active_trains"] == 1
    assert fleet["mean_active_delay_minutes"] == 2.5 and fleet["max_active_delay_minutes"] == 5
    clock[0] += timedelta(microseconds=1)
    assert get(request_api, "/trains/12301/eta")["status"] == "stale"
    assert get(request_api, "/stations/DKAE/arrivals")["arrivals"] == []
    assert (
        get(request_api, "/stations/DKAE/arrivals?include_stale=true")["arrivals"][0]["status"]
        == "stale"
    )


def test_current_journey_history_pagination_and_future_exclusion(
    db, request_api, clock, send_train
):
    old = send_train(end=NOW - timedelta(minutes=20))
    current = send_train(end=NOW - timedelta(seconds=10))
    # Same journey's second point, with an unchanged clock and five more seconds stopped.
    second = current | {
        "id": str(uuid4()),
        "timestamp": (NOW - timedelta(seconds=5)).isoformat(),
        "delay_minutes": current["delay_minutes"] + 5 / 60,
    }
    assert request_api("POST", "/ingest/position", second).status_code == 201
    send_train(end=NOW + timedelta(minutes=1))  # future sample must not replace current journey
    first_page = get(request_api, "/trains/12301/history?limit=1")
    assert first_page["journey_id"] == current["journey_id"]
    assert [p["id"] for p in first_page["positions"]] == [current["id"]]
    after = first_page["next_after"]
    page2 = get(request_api, f"/trains/12301/history?limit=1&after={after}")
    assert [p["id"] for p in page2["positions"]] == [second["id"]]
    assert page2["next_after"] is None
    assert (
        get(request_api, f"/trains/12301/history?journey_id={old['journey_id']}")["positions"][0][
            "id"
        ]
        == old["id"]
    )
    assert get(request_api, "/trains/12301/eta")["position_id"] == second["id"]


def test_overnight_dwell_and_terminal_predictions(db, request_api, clock, send_train):
    # Karnataka Express historical journey lasts 39 h 10 min, spans day 1 to day 3.
    send_train(index=3)
    eta = get(request_api, "/trains/12627/eta")
    assert datetime.fromisoformat(eta["stations"][-1]["scheduled_arrival"]) == (
        NOW - timedelta(minutes=10) + timedelta(hours=39, minutes=10)
    )
    # At DKAE dwell, its arrival is past; only later stations are upcoming.
    send_train(elapsed=1530, nominal=1230)
    eta = get(request_api, "/trains/12301/eta")
    assert "DKAE" not in [s["station_code"] for s in eta["stations"]]
    # Terminal is 61500 seconds after origin, then five minutes of delay.
    send_train(elapsed=61800, nominal=61500, end=NOW + timedelta(seconds=1))
    clock[0] += timedelta(seconds=1)
    terminal = get(request_api, "/trains/12301/eta")
    assert terminal["status"] == "completed" and terminal["stations"] == []
    assert terminal["features"]["distance_remaining_next_station_km"] == 0


def test_legacy_anchor_is_stable_and_explicitly_inferred(db, request_api, clock, send_train):
    payload = send_train(journey_started_at=None)
    first = get(request_api, "/trains/12301/eta")
    later = payload | {
        "id": str(uuid4()),
        "timestamp": (NOW + timedelta(seconds=10)).isoformat(),
        "delay_minutes": payload["delay_minutes"] + 10 / 60,
    }
    assert request_api("POST", "/ingest/position", later).status_code == 201
    clock[0] += timedelta(seconds=10)
    second = get(request_api, "/trains/12301/eta")
    assert first["timing_basis"] == second["timing_basis"] == "inferred_from_first_position"
    assert first["journey_started_at"] == second["journey_started_at"]
    assert second["features"]["minutes_since_last_station"] is None


def test_hourly_lookup_uses_next_station_and_local_day_not_legacy_bucket(db, send_train):
    send_train()
    for hour, day, average in [(0, 4, 12.5), (-1, 4, 99), (0, 3, 88), (1, 4, 77)]:
        db.add(
            HistoricalDelay(
                train_number="12301",
                station_code="DKAE",
                day_of_week=day,
                hour_of_day=hour,
                avg_delay_minutes=average,
                sample_count=8,
            )
        )
    db.flush()
    features = build_eta(db, "12301", NOW).features
    assert features.historical_avg_delay_minutes == 12.5 and features.historical_sample_count == 8


def test_last_station_observation_excludes_other_journeys_and_future(db, request_api, send_train):
    old = send_train(elapsed=1200, nominal=1200, end=NOW - timedelta(minutes=10))
    current = send_train(elapsed=1200, nominal=1200, end=NOW - timedelta(seconds=30))
    later = current | {"id": str(uuid4()), "timestamp": NOW.isoformat(), "delay_minutes": 0.5}
    assert request_api("POST", "/ingest/position", later).status_code == 201
    feature = build_eta(db, "12301", NOW).features
    assert old["journey_id"] != current["journey_id"]
    assert feature.minutes_since_last_station == 0.5


def test_congestion_selects_latest_train_before_section_filter(db, send_train):
    # Direct DB fixtures isolate query selection. Older matching-section points cannot
    # survive when a train's latest sample is on another section or in a new journey.
    current = send_train()
    send_train(index=1, end=NOW - timedelta(minutes=1))
    older = db.scalar(select(LivePosition).where(LivePosition.train_number == "12621"))
    older.last_station, older.next_station = "HWH", "DKAE"
    own = db.scalar(select(LivePosition).where(LivePosition.id == current["id"]))
    older.lat, older.lon = own.lat, own.lon
    db.flush()
    stops = route_stops(db, get_route(db, "12301"))
    assert compute_features(db, own, stops).congestion_index == 1
    send_train(index=1, end=NOW)  # new journey on MAS/BZA
    assert len(latest_positions(db, NOW)) == 2
    assert compute_features(db, own, stops).congestion_index == 0


@pytest.mark.parametrize(
    "path,status",
    [
        ("/trains/99999/eta", 404),
        ("/trains/99999/history", 404),
        ("/trains/abc/eta", 422),
        ("/stations/FAKE/arrivals", 404),
        ("/trains/12301/history?limit=0", 422),
        ("/trains/12301/history?limit=1001", 422),
        ("/trains/12301/history?after=2026-09-17T00:00:00", 422),
        ("/trains/12301/history?journey_id=00000000-0000-0000-0000-000000000001", 404),
    ],
)
def test_read_errors(db, request_api, clock, path, status):
    assert request_api("GET", path, None).status_code == status


def test_journey_start_validation(db, request_api, send_train):
    first = send_train()
    changed = first | {
        "id": str(uuid4()),
        "timestamp": (NOW + timedelta(seconds=5)).isoformat(),
        "journey_started_at": (NOW - timedelta(minutes=9)).isoformat(),
    }
    assert request_api("POST", "/ingest/position", changed).status_code == 409
    changed["journey_started_at"] = (NOW + timedelta(days=1)).isoformat()
    assert request_api("POST", "/ingest/position", changed).status_code == 422


def test_persisted_event_features_exclude_expired_future_and_other_journeys(
    db, request_api, clock, send_train
):
    position = send_train()
    for seconds, severity, journey in [
        (0, 2, position["journey_id"]),
        (-119, 3, position["journey_id"]),
        (-120, 3, position["journey_id"]),
        (1, 3, position["journey_id"]),
        (0, 3, str(uuid4())),
    ]:
        payload = dict(
            id=str(uuid4()),
            journey_id=journey,
            train_number="12301",
            timestamp=(NOW + timedelta(seconds=seconds)).isoformat(),
            event_type="weather",
            severity=severity,
            duration_seconds=120,
            description="Synthetic test event",
        )
        assert request_api("POST", "/ingest/event", payload).status_code == 201
    features = get(request_api, "/trains/12301/eta")["features"]
    assert features["active_event_count"] == 2
    assert features["active_event_severity_sum"] == 5
    assert features["active_event_max_severity"] == 3


def test_station_board_orders_multiple_arrivals_and_uses_same_baseline(
    db, request_api, clock, send_train
):
    send_train(index=0)
    send_train(index=1)
    send_train(index=3)
    rows = get(request_api, "/stations/NDLS/arrivals")["arrivals"]
    assert len(rows) == 3
    assert [r["eta"] for r in rows] == sorted(r["eta"] for r in rows)
    for row in rows:
        eta = get(request_api, f"/trains/{row['train_number']}/eta")
        assert row["eta"] == eta["stations"][-1]["baseline_eta"]


def test_read_database_failure_is_sanitized(request_api):
    from sqlalchemy.exc import OperationalError

    from app.database import get_session

    def unavailable():
        raise OperationalError("private SQL", {}, Exception("secret-password"))

    app.dependency_overrides[get_session] = unavailable
    try:
        for path in [
            "/trains",
            "/trains/12301/eta",
            "/trains/12301/history",
            "/stations/NDLS/arrivals",
            "/control/fleet-status",
        ]:
            response = request_api("GET", path, None)
            assert response.status_code == 503
            assert response.json() == {"detail": "Telemetry store unavailable"}
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_ml_fallback_preserves_baseline_and_legacy_contract(
    db, request_api, clock, send_train, monkeypatch
):
    import app.eta as eta_module

    send_train()
    monkeypatch.setattr(eta_module, "get_predictor", lambda: None)
    result = get(request_api, "/trains/12301/eta")
    assert result["ml_status"] == "unavailable"
    assert result["eta_ml_minutes"] is None
    assert result["eta_baseline_minutes"] == 15
    for station in result["stations"]:
        assert station["eta"] == station["baseline_eta"]
        assert station["explanation"] is None and station["model_version"] is None


def test_ml_only_predicts_next_station_and_matches_station_board(
    db, request_api, clock, send_train
):
    send_train()
    result = get(request_api, "/trains/12301/eta")
    assert result["ml_status"] == "ready"
    assert result["stations"][0]["ml_eta"] is not None
    for station in result["stations"][1:]:
        assert station["ml_eta"] is None
        assert station["eta"] == station["baseline_eta"]
    board = get(request_api, "/stations/DKAE/arrivals")["arrivals"][0]
    assert board["eta"] == result["stations"][0]["eta"]
    assert board["explanation"] == result["stations"][0]["explanation"]


def test_legacy_timing_and_out_of_domain_do_not_claim_model_output(
    db, request_api, clock, send_train
):
    send_train(journey_started_at=None, end=NOW - timedelta(seconds=1))
    assert get(request_api, "/trains/12301/eta")["ml_status"] == "legacy_timing"
    send_train(elapsed=1000000, nominal=300)
    result = get(request_api, "/trains/12301/eta")
    assert result["ml_status"] == "outside_training_domain"
    assert result["eta_ml_minutes"] is None


def test_prediction_failure_is_explicit_and_does_not_break_baseline(
    db, request_api, clock, send_train, monkeypatch
):
    import app.eta as eta_module

    class BrokenPredictor:
        def explain(self, _features):
            raise ValueError("Nonfinite model output")

    send_train()
    monkeypatch.setattr(eta_module, "get_predictor", lambda: BrokenPredictor())
    result = get(request_api, "/trains/12301/eta")
    assert result["ml_status"] == "prediction_error"
    assert result["eta_ml_minutes"] is None
    assert result["stations"][0]["eta"] == result["stations"][0]["baseline_eta"]


def test_ml_arrival_floor_keeps_shap_adjustment_reconcilable(
    db, request_api, clock, send_train, monkeypatch
):
    import app.eta as eta_module
    from app.read_schemas import ModelExplanation

    class EarlyPredictor:
        version = "test-clipping"

        def explain(self, features):
            return ModelExplanation(
                base_value_minutes=-features.current_delay_minutes,
                contributions=[],
                raw_residual_minutes=-features.current_delay_minutes,
                current_delay_minutes=features.current_delay_minutes,
                clipping_adjustment_minutes=0,
                predicted_delay_minutes=0,
            )

    send_train(elapsed=1800, nominal=300)
    monkeypatch.setattr(eta_module, "get_predictor", lambda: EarlyPredictor())
    result = get(request_api, "/trains/12301/eta")
    assert result["eta_ml_minutes"] == 0
    first = result["stations"][0]
    assert datetime.fromisoformat(first["ml_eta"]) == NOW
    explanation = first["explanation"]
    assert explanation["clipping_adjustment_minutes"] == 10
    assert (
        explanation["current_delay_minutes"]
        + explanation["raw_residual_minutes"]
        + explanation["clipping_adjustment_minutes"]
        == first["predicted_delay_minutes"]
    )


def test_eta_snapshot_includes_matching_position_and_asof_events(
    db, request_api, clock, send_train
):
    position = send_train()
    event = dict(
        id=str(uuid4()),
        journey_id=position["journey_id"],
        train_number="12301",
        timestamp=position["timestamp"],
        event_type="weather",
        severity=2,
        duration_seconds=60,
        description="Synthetic weather",
    )
    assert request_api("POST", "/ingest/event", event).status_code == 201
    for extra in [
        dict(event, id=str(uuid4()), journey_id=str(uuid4())),
        dict(event, id=str(uuid4()), timestamp=(NOW + timedelta(seconds=1)).isoformat()),
    ]:
        assert request_api("POST", "/ingest/event", extra).status_code == 201
    eta = get(request_api, "/trains/12301/eta")
    assert eta["position"]["id"] == eta["position_id"] == position["id"]
    assert eta["position"]["journey_id"] == eta["journey_id"]
    assert eta["position"]["timestamp"] == eta["as_of"]
    assert [e["id"] for e in eta["active_events"]] == [event["id"]]
    assert eta["features"]["active_event_count"] == len(eta["active_events"])
