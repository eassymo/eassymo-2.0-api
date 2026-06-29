from app.config import database


def insert(payload):
    return database.db["Photos"].insert_one(payload)
