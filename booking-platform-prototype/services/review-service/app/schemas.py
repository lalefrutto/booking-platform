import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    booking_id: str
    user_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = ""


class ReviewOut(BaseModel):
    booking_id: str
    user_id: str
    hotel_id: str
    rating: int
    comment: str
    created_at: datetime.datetime
