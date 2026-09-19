import uuid
import datetime
from decimal import Decimal
from typing import List

from pydantic import BaseModel


class HotelCreate(BaseModel):
    name: str
    city: str
    description: str = ""


class RoomCreate(BaseModel):
    room_type: str
    price_per_night: Decimal
    capacity: int = 2


class RoomOut(BaseModel):
    id: uuid.UUID
    hotel_id: uuid.UUID
    room_type: str
    price_per_night: Decimal
    capacity: int

    class Config:
        from_attributes = True


class HotelOut(BaseModel):
    id: uuid.UUID
    name: str
    city: str
    description: str
    rooms: List[RoomOut] = []

    class Config:
        from_attributes = True


class AvailabilityOut(BaseModel):
    room_id: uuid.UUID
    check_in: datetime.date
    check_out: datetime.date
    available: bool
    price_per_night: Decimal
    source: str  # "cache" | "db"
