from app.config import database
from bson import ObjectId
from pymongo import ReturnDocument
from typing import Optional


def find_by_phone(phone: str) -> Optional[dict]:
    return database.db["GuestDeliveryProfiles"].find_one({"phone": phone})


def find_by_token(token: str) -> Optional[dict]:
    return database.db["GuestDeliveryProfiles"].find_one({"token": token})


def insert(payload: dict) -> dict:
    result = database.db["GuestDeliveryProfiles"].insert_one(payload)
    return database.db["GuestDeliveryProfiles"].find_one({"_id": result.inserted_id})


def update(filters: dict, new_data: dict) -> Optional[dict]:
    return database.db["GuestDeliveryProfiles"].find_one_and_update(
        filters,
        {"$set": new_data},
        return_document=ReturnDocument.AFTER
    )
