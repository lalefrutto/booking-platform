import uuid
import datetime

from sqlalchemy import Column, Numeric, Date, DateTime, Enum, Text
from sqlalchemy.dialects.postgresql import UUID

from .database import Base

BOOKING_STATUSES = ("PENDING", "CONFIRMED", "CANCELLED")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    hotel_id = Column(UUID(as_uuid=True), nullable=False)
    room_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(Enum(*BOOKING_STATUSES, name="booking_status"), nullable=False, default="PENDING")
    cancellation_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
