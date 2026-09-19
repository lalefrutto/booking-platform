import uuid
import logging
import datetime

from fastapi import FastAPI, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_

from . import models, schemas
from .database import get_db
from .cache import availability_key, get_cached_availability, set_cached_availability
from .kafka_consumer import start_consumer_thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("catalog-service")

app = FastAPI(title="Catalog Service", version="1.0.0")


@app.on_event("startup")
def on_startup():
    start_consumer_thread()
    logger.info("catalog-service started, consumer running")


@app.get("/health")
@app.get("/hotels/health")  # алиас: /health снаружи недостижим через префиксный роутинг Traefik
@app.get("/rooms/health")  # алиас: /health снаружи недостижим через префиксный роутинг Traefik
def health():
    return {"status": "ok", "service": "catalog-service"}


@app.post("/hotels", response_model=schemas.HotelOut, status_code=status.HTTP_201_CREATED)
def create_hotel(payload: schemas.HotelCreate, db: Session = Depends(get_db)):
    hotel = models.Hotel(**payload.model_dump())
    db.add(hotel)
    db.commit()
    db.refresh(hotel)
    return hotel


@app.get("/hotels", response_model=list[schemas.HotelOut])
def list_hotels(city: str | None = Query(default=None), db: Session = Depends(get_db)):
    query = db.query(models.Hotel).options(joinedload(models.Hotel.rooms))
    if city:
        query = query.filter(models.Hotel.city.ilike(f"%{city}%"))
    return query.all()


@app.get("/hotels/{hotel_id}", response_model=schemas.HotelOut)
def get_hotel(hotel_id: uuid.UUID, db: Session = Depends(get_db)):
    hotel = (
        db.query(models.Hotel)
        .options(joinedload(models.Hotel.rooms))
        .filter(models.Hotel.id == hotel_id)
        .first()
    )
    if not hotel:
        raise HTTPException(status_code=404, detail="Отель не найден")
    return hotel


@app.post("/hotels/{hotel_id}/rooms", response_model=schemas.RoomOut, status_code=status.HTTP_201_CREATED)
def add_room(hotel_id: uuid.UUID, payload: schemas.RoomCreate, db: Session = Depends(get_db)):
    hotel = db.query(models.Hotel).filter(models.Hotel.id == hotel_id).first()
    if not hotel:
        raise HTTPException(status_code=404, detail="Отель не найден")
    room = models.Room(hotel_id=hotel_id, **payload.model_dump())
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@app.get("/rooms/{room_id}", response_model=schemas.RoomOut)
def get_room(room_id: uuid.UUID, db: Session = Depends(get_db)):
    """Используется Booking Service для получения цены за ночь."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Номер не найден")
    return room


@app.get("/rooms/{room_id}/availability", response_model=schemas.AvailabilityOut)
def check_availability(
    room_id: uuid.UUID,
    check_in: datetime.date = Query(...),
    check_out: datetime.date = Query(...),
    db: Session = Depends(get_db),
):
    if check_out <= check_in:
        raise HTTPException(status_code=400, detail="check_out должен быть позже check_in")

    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Номер не найден")

    key = availability_key(str(room_id), check_in.isoformat(), check_out.isoformat())
    cached = get_cached_availability(key)
    if cached is not None:
        return schemas.AvailabilityOut(
            room_id=room_id,
            check_in=check_in,
            check_out=check_out,
            available=cached["available"],
            price_per_night=room.price_per_night,
            source="cache",
        )

    # Пересечение интервалов: existing.check_in < new.check_out AND existing.check_out > new.check_in
    overlap = (
        db.query(models.BlockedDateRange)
        .filter(
            models.BlockedDateRange.room_id == room_id,
            and_(
                models.BlockedDateRange.check_in < check_out,
                models.BlockedDateRange.check_out > check_in,
            ),
        )
        .first()
    )
    available = overlap is None
    set_cached_availability(key, {"available": available})

    return schemas.AvailabilityOut(
        room_id=room_id,
        check_in=check_in,
        check_out=check_out,
        available=available,
        price_per_night=room.price_per_night,
        source="db",
    )
