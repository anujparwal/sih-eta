"""Ordered, versioned model inputs shared by training and serving."""

import math

from app.read_schemas import Features

FEATURE_VERSION = "next-station-v1"
# Unversioned historical_delays cannot establish what was known at a past sample.
# Keep them in the public feature contract, but exclude them from this model.
FEATURE_NAMES = [
    "minutes_since_last_station",
    "distance_remaining_next_station_km",
    "current_delay_minutes",
    "historical_day_of_week",
    "historical_hour_of_day",
    "active_event_count",
    "active_event_severity_sum",
    "active_event_max_severity",
    "congestion_index",
]


def feature_vector(features: Features) -> list[float]:
    values = []
    for name in FEATURE_NAMES:
        value = getattr(features, name)
        if value is None:
            values.append(float("nan"))
        elif not math.isfinite(value):
            raise ValueError(f"Nonfinite model feature: {name}")
        else:
            values.append(float(value))
    return values
