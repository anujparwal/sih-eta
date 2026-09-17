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
