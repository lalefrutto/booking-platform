import uuid
import logging

from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from . import models, schemas, auth
from .database import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("user-service")

app = FastAPI(title="User Service", version="1.0.0")


@app.on_event("startup")
def on_startup():
    # Схема накатывается Alembic-миграциями до старта uvicorn (см. Dockerfile).
    logger.info("user-service started")


@app.get("/health")
@app.get("/users/health")  # алиас: /health снаружи недостижим через префиксный роутинг Traefik
def health():
    return {"status": "ok", "service": "user-service"}


@app.post("/users/register", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    user = models.User(
        email=payload.email,
        password_hash=auth.hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует")
    db.refresh(user)
    return user


@app.post("/users/login", response_model=schemas.Token)
def login(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    token = auth.create_access_token(user.id, user.role)
    return schemas.Token(access_token=token)


@app.get("/users/me", response_model=schemas.UserOut)
def read_me(token_payload: dict = Depends(auth.decode_token), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == uuid.UUID(token_payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@app.get("/users/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: uuid.UUID, db: Session = Depends(get_db)):
    """Внутренний эндпоинт: используется другими сервисами для получения профиля."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user
