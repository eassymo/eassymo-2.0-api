"""Pickup codes live in their own collection, never on the Orders document, so they cannot leak
through the many places an order is serialized."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo import ASCENDING, ReturnDocument

from app.config import database

COLLECTION = "order_pickup_codes"
db = database.db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_indexes() -> None:
    if db is None:
        return
    db[COLLECTION].create_index([("order_id", ASCENDING)], unique=True)


def upsert_code(order_id: str, code: str) -> None:
    """Creates or replaces the order's code and clears every counter."""
    db[COLLECTION].update_one(
        {"order_id": order_id},
        {"$set": {"order_id": order_id, "code": code, "attempts": 0, "total_attempts": 0,
                  "locked_until": None, "retired": False, "created_at": _now()}},
        upsert=True,
    )


def find(order_id: str) -> Optional[Dict[str, Any]]:
    return db[COLLECTION].find_one({"order_id": order_id}, {"_id": 0})


def record_wrong_attempt(order_id: str) -> Optional[Dict[str, Any]]:
    """Atomic: two simultaneous wrong guesses both count."""
    return db[COLLECTION].find_one_and_update(
        {"order_id": order_id},
        {"$inc": {"attempts": 1, "total_attempts": 1}},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )


def lock_until(order_id: str, until: datetime) -> None:
    db[COLLECTION].update_one({"order_id": order_id}, {"$set": {"locked_until": until, "attempts": 0}})


def retire(order_id: str) -> None:
    db[COLLECTION].update_one({"order_id": order_id}, {"$set": {"retired": True}})


def delete(order_id: str) -> None:
    db[COLLECTION].delete_one({"order_id": order_id})
