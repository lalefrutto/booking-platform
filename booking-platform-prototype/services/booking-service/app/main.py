import uuid
import logging
from decimal import Decimal

from fastapi import FastAPI, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from . import models, schemas
from .database import get_db
from .catalog_client import check_availability, CatalogUnavailableError, RoomNotFoundError
from .kafka_producer import publish_event
from .kafka_consumer import start_consumer_thread
from .locks import room_lock, RoomLockBusy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("booking-service")

app = FastAPI(title="Booking Service", version="1.0.0")


@app.on_event("startup")
def on_startup():
    start_consumer_thread()
    logger.info("booking-service started, consumer running")


@app.get("/health")
@app.get("/bookings/health")  # алиас: /health снаружи недостижим через префиксный роутинг Traefik
def health():
    return {"status": "ok", "service": "booking-service"}


@app.post("/bookings", response_model=schemas.BookingOut, status_code=status.HTTP_202_ACCEPTED)
def create_booking(payload: schemas.BookingCreate, db: Session = Depends(get_db)):
    if payload.check_out <= payload.check_in:
        raise HTTPException(status_code=400, detail="check_out должен быть позже check_in")

    # Шаг 0: короткая распределённая блокировка на (номер, даты). Закрывает окно
    # между проверкой доступности и коммитом брони — без неё два параллельных
    # запроса получают "available: true" и создают две брони на одни даты.
    try:
        lock = room_lock(
            str(payload.room_id), payload.check_in.isoformat(), payload.check_out.isoformat()
        )
        lock.__enter__()
    except RoomLockBusy:
        raise HTTPException(
            status_code=409,
            detail="Этот номер на выбранные даты сейчас бронирует другой гость, попробуйте ещё раз",
        )

    try:
        # Шаг 1: синхронная проверка доступности и цены в Catalog Service
        try:
            availability = check_availability(
                str(payload.room_id), payload.check_in.isoformat(), payload.check_out.isoformat()
            )
        except RoomNotFoundError:
            raise HTTPException(status_code=404, detail="Номер не найден в каталоге")
        except CatalogUnavailableError:
            raise HTTPException(status_code=503, detail="Catalog Service недоступен, попробуйте позже")

        if not availability["available"]:
            raise HTTPException(status_code=409, detail="Номер недоступен на выбранные даты")

        # Вторая линия защиты: активная бронь на пересекающиеся даты в собственной БД.
        # Catalog обновляет свою read-модель только по booking.confirmed, поэтому
        # ещё не оплаченные (PENDING) брони видны только здесь.
        conflict = (
            db.query(models.Booking)
            .filter(
                models.Booking.room_id == payload.room_id,
                models.Booking.status.in_(("PENDING", "CONFIRMED")),
                models.Booking.check_in < payload.check_out,
                models.Booking.check_out > payload.check_in,
            )
            .first()
        )
        if conflict:
            raise HTTPException(status_code=409, detail="Номер недоступен на выбранные даты")

        nights = (payload.check_out - payload.check_in).days
        # Catalog отдаёт price_per_night строкой (Pydantic сериализует Decimal в JSON
        # как строку) — без явного приведения к Decimal получилось бы повторение строки.
        amount = Decimal(str(availability["price_per_night"])) * nights

        # Шаг 2: создать бронь в статусе PENDING (начало саги)
        booking = models.Booking(
            user_id=payload.user_id,
            hotel_id=payload.hotel_id,
            room_id=payload.room_id,
            check_in=payload.check_in,
            check_out=payload.check_out,
            amount=amount,
            status="PENDING",
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)

        # Шаг 3: опубликовать booking.created — запускает обработку платежа
        # (choreography-based saga: Payment Service сам подписан на этот топик)
        publish_event(
            "booking.created",
            {
                "booking_id": str(booking.id),
                "user_id": str(booking.user_id),
                "hotel_id": str(booking.hotel_id),
                "room_id": str(booking.room_id),
                "check_in": booking.check_in.isoformat(),
                "check_out": booking.check_out.isoformat(),
                "amount": str(booking.amount),
            },
        )
        return booking
    finally:
        lock.__exit__(None, None, None)


@app.get("/bookings/{booking_id}", response_model=schemas.BookingOut)
def get_booking(booking_id: uuid.UUID, db: Session = Depends(get_db)):
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Бронирование не найдено")
    return booking


@app.get("/bookings", response_model=list[schemas.BookingOut])
def list_bookings(user_id: uuid.UUID = Query(...), db: Session = Depends(get_db)):
    return db.query(models.Booking).filter(models.Booking.user_id == user_id).order_by(models.Booking.created_at.desc()).all()


@app.post("/bookings/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel_booking(booking_id: uuid.UUID, db: Session = Depends(get_db)):
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Бронирование не найдено")
    if booking.status == "CONFIRMED":
        # отмена уже подтверждённой брони — отдельная бизнес-политика (сборы и т.д.),
        # для прототипа разрешаем и просто эмитим событие с релизом номера
        pass
    elif booking.status == "CANCELLED":
        raise HTTPException(status_code=409, detail="Бронирование уже отменено")

    booking.status = "CANCELLED"
    booking.cancellation_reason = "cancelled_by_user"
    db.commit()
    db.refresh(booking)

    publish_event(
        "booking.cancelled",
        {
            "booking_id": str(booking.id),
            "user_id": str(booking.user_id),
            "room_id": str(booking.room_id),
            "reason": booking.cancellation_reason,
        },
    )
    return booking
