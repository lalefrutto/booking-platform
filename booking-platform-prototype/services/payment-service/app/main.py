import uuid
import logging

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from . import models, schemas
from .database import get_db
from .kafka_consumer import start_consumer_thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("payment-service")

app = FastAPI(title="Payment Service", version="1.0.0")


@app.on_event("startup")
def on_startup():
    start_consumer_thread()
    logger.info("payment-service started, consumer running")


@app.get("/health")
@app.get("/payments/health")  # алиас: /health снаружи недостижим через префиксный роутинг Traefik
def health():
    return {"status": "ok", "service": "payment-service"}


@app.get("/payments/{booking_id}", response_model=schemas.PaymentOut)
def get_payment(booking_id: uuid.UUID, db: Session = Depends(get_db)):
    payment = db.query(models.Payment).filter(models.Payment.booking_id == booking_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Платёж для данного бронирования не найден")
    return payment
