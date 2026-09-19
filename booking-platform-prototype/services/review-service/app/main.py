import logging
import datetime

from fastapi import FastAPI, HTTPException, status

from . import schemas
from .database import reviews_collection, eligibility_collection
from .kafka_consumer import start_consumer_thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("review-service")

app = FastAPI(title="Review Service", version="1.0.0")


@app.on_event("startup")
def on_startup():
    start_consumer_thread()
    logger.info("review-service started, consumer running")


@app.get("/health")
@app.get("/reviews/health")  # алиас: /health снаружи недостижим через префиксный роутинг Traefik
def health():
    return {"status": "ok", "service": "review-service"}


@app.post("/reviews", status_code=status.HTTP_201_CREATED)
def create_review(payload: schemas.ReviewCreate):
    eligibility = eligibility_collection.find_one({"booking_id": payload.booking_id})
    if not eligibility:
        raise HTTPException(
            status_code=403,
            detail="Отзыв можно оставить только по подтверждённому бронированию",
        )
    if eligibility.get("reviewed"):
        raise HTTPException(status_code=409, detail="Отзыв по этому бронированию уже оставлен")

    review_doc = {
        "booking_id": payload.booking_id,
        "user_id": payload.user_id,
        "hotel_id": eligibility["hotel_id"],
        "rating": payload.rating,
        "comment": payload.comment,
        "created_at": datetime.datetime.utcnow(),
    }
    reviews_collection.insert_one(review_doc)
    eligibility_collection.update_one({"booking_id": payload.booking_id}, {"$set": {"reviewed": True}})
    review_doc.pop("_id", None)
    return review_doc


@app.get("/reviews/hotel/{hotel_id}")
def list_hotel_reviews(hotel_id: str):
    reviews = list(reviews_collection.find({"hotel_id": hotel_id}, {"_id": 0}).sort("created_at", -1))
    avg_rating = round(sum(r["rating"] for r in reviews) / len(reviews), 2) if reviews else None
    return {"hotel_id": hotel_id, "average_rating": avg_rating, "total_reviews": len(reviews), "reviews": reviews}
