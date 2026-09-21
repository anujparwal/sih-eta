"""Hand-calculated feature expectations, independent of PostgreSQL and the simulator."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.features import active_events, congestion_count, distance_km, feature_values
from app.models import Event, HistoricalDelay, LivePosition, RouteStop

NOW = datetime(2026, 9, 17, 18, 40, tzinfo=UTC)  # Friday 00:10 IST, Thursday UTC.
JOURNEY = uuid4()


def sample(**changes):
    fields = dict(
        train_number="12301",
        journey_id=JOURNEY,
        timestamp=NOW,
        lat=0,
        lon=0,
        last_station="A",
        next_station="B",
        distance_km=4,
        delay_minutes=7,
    )
    return LivePosition(**(fields | changes))


def event(**changes):
    fields = dict(
        train_number="12301", journey_id=JOURNEY, timestamp=NOW, duration_seconds=120, severity=2
    )
    return Event(**(fields | changes))


def test_hand_calculated_features_and_ist_rollover():
    position = sample()
    result = feature_values(
        position,
        RouteStop(distance_km=10),
        NOW - timedelta(seconds=150),
        HistoricalDelay(avg_delay_minutes=12.5, sample_count=8),
        [event(), event(severity=3), event(timestamp=NOW - timedelta(seconds=120))],
        [sample(train_number="12621", lon=0.01)],
    )
    assert result.minutes_since_last_station == 2.5  # 150 / 60
    assert result.distance_remaining_next_station_km == 6  # 10 - 4
    assert result.current_delay_minutes == 7
    assert result.historical_avg_delay_minutes == 12.5
    assert result.historical_sample_count == 8
    assert (result.historical_day_of_week, result.historical_hour_of_day) == (4, 0)
    assert (
        result.active_event_count,
        result.active_event_severity_sum,
        result.active_event_max_severity,
    ) == (2, 5, 3)
    assert result.congestion_index == 1
    assert result.missing == []


def test_unknown_features_stay_null_not_invented_zero():
    result = feature_values(sample(), RouteStop(distance_km=10), None, None, [], [])
    assert result.minutes_since_last_station is None
    assert result.historical_avg_delay_minutes is None
    assert result.historical_sample_count == 0
    assert result.missing == ["minutes_since_last_station", "historical_avg_delay_minutes"]
    assert result.active_event_count == result.active_event_severity_sum == 0


def test_event_start_inclusive_end_exclusive_and_journey_scope():
    ongoing = event(timestamp=NOW - timedelta(seconds=119))
    assert active_events(
        sample(),
        [
            ongoing,
            event(timestamp=NOW - timedelta(seconds=120)),
            event(timestamp=NOW + timedelta(seconds=1)),
            event(journey_id=uuid4()),
            event(train_number="12621"),
        ],
    ) == [ongoing]
    assert active_events(sample(next_station=None), [ongoing]) == []


def test_congestion_distance_time_direction_and_section_boundaries():
    current = sample()
    # One degree of longitude at the equator is pi*6371.0088/180 = 111.195080 km.
    assert distance_km(current, sample(lon=1)) == pytest.approx(111.195080, abs=1e-6)
    others = [
        sample(train_number="12621", lon=0.01),  # 1.11195 km
        sample(
            train_number="12622",
            timestamp=NOW - timedelta(minutes=10),
            last_station="B",
            next_station="A",
        ),  # opposite direction counts
        sample(train_number="12627", lon=0.1),  # 11.1195 km: too far
        sample(train_number="12952", timestamp=NOW - timedelta(minutes=10, seconds=1)),
        sample(train_number="12953", timestamp=NOW + timedelta(seconds=1)),
        sample(train_number="11111", next_station="C"),
        sample(),
    ]  # never count self
    assert congestion_count(current, others, 5) == 2
    assert congestion_count(current, others, 1) == 1
    assert congestion_count(sample(next_station=None), others, 5) == 0


@pytest.mark.parametrize(
    "instant,weekday,hour",
    [
        ("2026-09-20T18:29:59.999999+00:00", 6, 23),
        ("2026-09-20T18:30:00+00:00", 0, 0),
        ("2026-12-31T18:30:00+00:00", 4, 0),
        ("2024-02-28T18:30:00+00:00", 3, 0),
        ("2026-09-21T00:00:00+05:30", 0, 0),
    ],
)
def test_history_bucket_at_ist_week_year_and_leap_day_boundaries(instant, weekday, hour):
    point = sample(timestamp=datetime.fromisoformat(instant))
    result = feature_values(point, RouteStop(distance_km=10), None, None, [], [])
    assert (result.historical_day_of_week, result.historical_hour_of_day) == (weekday, hour)
    assert result.as_of == point.timestamp


@pytest.mark.parametrize("remaining", [6, 0, -0.001])
def test_remaining_distance_never_negative(remaining):
    result = feature_values(sample(), RouteStop(distance_km=4 + remaining), NOW, None, [], [])
    assert result.distance_remaining_next_station_km == max(0, remaining)
    assert result.minutes_since_last_station == 0
    assert "minutes_since_last_station" not in result.missing


def test_terminal_features_have_no_next_stop_incidents_or_congestion():
    point = sample(next_station=None)
    result = feature_values(point, None, NOW - timedelta(minutes=2), None, [event()], [sample()])
    assert result.distance_remaining_next_station_km == 0
    assert result.historical_station_code is None
    assert result.active_event_count == result.active_event_severity_sum == 0
    assert result.active_event_max_severity == result.congestion_index == 0
    assert result.minutes_since_last_station == 2
    assert result.current_delay_minutes == 7


def test_measured_zero_history_is_not_missing():
    history = HistoricalDelay(avg_delay_minutes=0, sample_count=5)
    result = feature_values(sample(), RouteStop(distance_km=10), NOW, history, [], [])
    assert result.historical_avg_delay_minutes == 0
    assert result.historical_sample_count == 5
    assert result.missing == []


@pytest.mark.parametrize("microseconds,expected", [(-1, 0), (0, 1), (119999999, 1), (120000000, 0)])
def test_event_activity_at_microsecond_boundaries(microseconds, expected):
    point = sample(timestamp=NOW + timedelta(microseconds=microseconds))
    assert len(active_events(point, [event()])) == expected


def test_radius_is_inclusive_and_geographic_distance_wraps_at_dateline():
    point = sample()
    other = sample(train_number="12621", lon=0.01)
    radius = distance_km(point, other)
    assert congestion_count(point, [other], radius) == 1
    assert congestion_count(point, [other], radius - 1e-8) == 0
    assert distance_km(point, point) == 0
    assert distance_km(sample(lon=179.99), sample(lon=-179.99)) == pytest.approx(2.2239016)
    assert distance_km(sample(lon=180), point) == pytest.approx(20015.114442, abs=1e-6)
