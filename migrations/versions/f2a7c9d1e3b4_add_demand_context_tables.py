"""add_demand_context_tables

Revision ID: f2a7c9d1e3b4
Revises: e9a4c3d2b5f6
Create Date: 2026-07-28 15:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "f2a7c9d1e3b4"
down_revision = "e9a4c3d2b5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "local_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("expected_impact", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_local_events_date", "local_events", ["event_date"])
    op.create_index(
        "idx_local_events_impact_date",
        "local_events",
        ["expected_impact", "event_date"],
    )

    op.create_table(
        "weather_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("location_label", sa.String(length=160), nullable=True),
        sa.Column("condition", sa.String(length=80), nullable=True),
        sa.Column("description", sa.String(length=160), nullable=True),
        sa.Column("temp_min_c", sa.Numeric(5, 2), nullable=True),
        sa.Column("temp_max_c", sa.Numeric(5, 2), nullable=True),
        sa.Column("humidity_avg", sa.Numeric(5, 2), nullable=True),
        sa.Column("precipitation_probability", sa.Numeric(5, 2), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "forecast_date",
            "source",
            "location_label",
            name="uq_weather_snapshot_scope",
        ),
    )
    op.create_index("idx_weather_snapshot_date", "weather_snapshots", ["forecast_date"])


def downgrade():
    op.drop_index("idx_weather_snapshot_date", table_name="weather_snapshots")
    op.drop_table("weather_snapshots")
    op.drop_index("idx_local_events_impact_date", table_name="local_events")
    op.drop_index("idx_local_events_date", table_name="local_events")
    op.drop_table("local_events")
