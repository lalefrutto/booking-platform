import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationOut(BaseModel):
    booking_id: str
    user_id: Optional[str] = None
    event_type: str
    channel: str
    message: str
    created_at: datetime.datetime
