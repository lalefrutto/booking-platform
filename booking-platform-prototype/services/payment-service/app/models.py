import uuid
import datetime

from sqlalchemy import Column, Numeric, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID

from .database import Base

PAYMENT_STATUSES = ("COMPLETED", "FAILED")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(Enum(*PAYMENT_STATUSES, name="payment_status"), nullable=False)
    provider_ref = Column(String(64), nullable=True)  # мок-идентификатор транзакции у эквайера
    failure_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
