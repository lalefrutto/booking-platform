"""Начальная схема catalog-service: hotels, rooms, blocked_date_ranges.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hotels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Date(), nullable=True),
    )
    op.create_index("ix_hotels_city", "hotels", ["city"])

    op.create_table(
        "rooms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("hotel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_type", sa.String(length=120), nullable=False),
        sa.Column("price_per_night", sa.Numeric(10, 2), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"]),
    )
    op.create_index("ix_rooms_hotel_id", "rooms", ["hotel_id"])

    # Read-модель поверх событий booking.confirmed / booking.cancelled.
    op.create_table(
        "blocked_date_ranges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
    )
    op.create_index("ix_blocked_date_ranges_room_id", "blocked_date_ranges", ["room_id"])
    op.create_index(
        "ix_blocked_date_ranges_booking_id", "blocked_date_ranges", ["booking_id"], unique=True
    )


def downgrade() -> None:
    op.drop_table("blocked_date_ranges")
    op.drop_table("rooms")
    op.drop_table("hotels")
