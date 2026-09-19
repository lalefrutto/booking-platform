import uuid
import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class BookingCreate(BaseModel):
    user_id: uuid.UUID
    hotel_id: uuid.UUID
    room_id: uuid.UUID
    check_in: datetime.date
    check_out: datetime.date


class BookingOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    hotel_id: uuid.UUID
    room_id: uuid.UUID
    check_in: datetime.date
    check_out: datetime.date
    amount: Decimal
    status: str
    cancellation_reason: Optional[str] = None
    created_at: datetime.datetime

    class Config:
        from_attributes = True
