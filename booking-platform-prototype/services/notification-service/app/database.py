import os
from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongo:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "notification_log")

_client = MongoClient(MONGO_URL)
db = _client[MONGO_DB_NAME]
notifications_collection = db["notifications"]

# Индекс по user_id ускоряет выборку истории уведомлений пользователя.
notifications_collection.create_index("user_id")
notifications_collection.create_index("booking_id")
