import uuid
import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class PaymentOut(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    user_id: uuid.UUID
    amount: Decimal
    status: str
    provider_ref: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime.datetime

    class Config:
        from_attributes = True
