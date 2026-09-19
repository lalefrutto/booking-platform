import uuid
import datetime

from sqlalchemy import Column, String, Numeric, Integer, ForeignKey, Date, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base


class Hotel(Base):
    __tablename__ = "hotels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    city = Column(String(120), nullable=False, index=True)
    description = Column(Text, default="")
    created_at = Column(Date, default=datetime.date.today)

    rooms = relationship("Room", back_populates="hotel", cascade="all, delete-orphan")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id"), nullable=False, index=True)
    room_type = Column(String(120), nullable=False)
    price_per_night = Column(Numeric(10, 2), nullable=False)
    capacity = Column(Integer, nullable=False, default=2)

    hotel = relationship("Hotel", back_populates="rooms")


class BlockedDateRange(Base):
    """
    Собственная read-модель Catalog Service поверх событий booking.confirmed /
    booking.cancelled. Позволяет проверять доступность без синхронного вызова
    Booking Service (эвентуальная согласованность через Kafka).
    """
    __tablename__ = "blocked_date_ranges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=False, index=True)
    booking_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
