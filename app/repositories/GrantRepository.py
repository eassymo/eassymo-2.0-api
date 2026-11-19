from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument

from app.config import database

COLLECTION = "grants"


def _coll(collection=None):
    return collection if collection is not None else database.db[COLLECTION]


def find(filters: Dict[str, Any], collection=None) -> List[Dict[str, Any]]:
    return list(_coll(collection).find(filters, {"_id": 0}))


def find_by_key(key: str, collection=None) -> Optional[Dict[str, Any]]:
    return _coll(collection).find_one({"key": key}, {"_id": 0})


def active_keys(collection=None) -> set:
    return {doc["key"] for doc in _coll(collection).find({"active": {"$ne": False}}, {"key": 1})}


def update(key: str, fields: Dict[str, Any], collection=None) -> Optional[Dict[str, Any]]:
    return _coll(collection).find_one_and_update(
        {"key": key},
        {"$set": fields},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )


def upsert_missing(docs: List[Dict[str, Any]], collection=None) -> int:
    """Insert catalog docs whose key is not stored yet. Never touches existing docs,
    so names and descriptions edited by super admins survive re-seeding."""
    coll = _coll(collection)
    keys = [d["key"] for d in docs]
    existing = {d["key"] for d in coll.find({"key": {"$in": keys}}, {"key": 1})}
    now = datetime.now(timezone.utc)
    missing = [{**d, "created_at": now, "updated_at": now} for d in docs if d["key"] not in existing]
    if missing:
        coll.insert_many(missing)
    return len(missing)
