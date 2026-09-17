"""Add optional journey anchors and hourly historical buckets without inventing history.

Revision ID: 86d3e901aa21
Revises: 612d6a4111d6
"""

import sqlalchemy as sa
from alembic import op

revision = "86d3e901aa21"
down_revision = "612d6a4111d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("live_positions", sa.Column("journey_started_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_position_journey_start", "live_positions", "journey_started_at <= timestamp"
    )
    op.add_column(
        "historical_delays",
        sa.Column("hour_of_day", sa.Integer(), nullable=False, server_default="-1"),
    )
    # PostgreSQL's generated name for the original unnamed three-column constraint.
    op.drop_constraint(
        "historical_delays_train_number_station_code_day_of_week_key",
        "historical_delays",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_historical_delay_hour",
        "historical_delays",
        ["train_number", "station_code", "day_of_week", "hour_of_day"],
    )
    op.create_check_constraint(
        "ck_historical_delay_hour", "historical_delays", "hour_of_day BETWEEN -1 AND 23"
    )


def downgrade() -> None:
    # Hourly buckets cannot be losslessly represented by Phase 2's daily schema.
    # Refuse to discard or mix measured data; the operator must export it first.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM historical_delays WHERE hour_of_day <> -1) THEN
            RAISE EXCEPTION 'Export and remove hourly history before downgrading to Phase 2';
          END IF;
        END $$;
    """)
    op.drop_constraint("ck_historical_delay_hour", "historical_delays", type_="check")
    op.drop_constraint("uq_historical_delay_hour", "historical_delays", type_="unique")
    op.drop_column("historical_delays", "hour_of_day")
    op.create_unique_constraint(
        "historical_delays_train_number_station_code_day_of_week_key",
        "historical_delays",
        ["train_number", "station_code", "day_of_week"],
    )
    op.drop_constraint("ck_position_journey_start", "live_positions", type_="check")
    op.drop_column("live_positions", "journey_started_at")
