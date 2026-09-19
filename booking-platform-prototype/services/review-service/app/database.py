import os
from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongo:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "reviews")

_client = MongoClient(MONGO_URL)
db = _client[MONGO_DB_NAME]

reviews_collection = db["reviews"]
eligibility_collection = db["review_eligibility"]

reviews_collection.create_index("hotel_id")
eligibility_collection.create_index("booking_id", unique=True)
