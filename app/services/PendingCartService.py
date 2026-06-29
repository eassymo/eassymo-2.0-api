from app.repositories import PendingCartRepository as pendingCartRepository
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from pymongo.errors import PyMongoError
from fastapi import HTTPException

TTL_HOURS = 24


def _serialize(doc: dict) -> dict:
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    for field in ("saved_at", "updated_at", "created_at"):
        if isinstance(doc.get(field), datetime):
            doc[field] = doc[field].isoformat()
    return doc


def _is_expired(doc: dict) -> bool:
    saved_at = doc.get("saved_at")
    if saved_at is None:
        return True
    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - saved_at > timedelta(hours=TTL_HOURS)


def save(user_uid: str, group_id: str, vehicle_id: str | None, part_list: list) -> dict:
    try:
        payload = {
            "user_uid": user_uid,
            "group_id": group_id,
            "vehicle_id": vehicle_id,
            "part_list": part_list,
        }
        doc = pendingCartRepository.upsert(user_uid, group_id, payload)
        return _serialize(doc)
    except PyMongoError as err:
        raise HTTPException(status_code=500, detail=f"Error saving pending cart: {err}")


def get(user_uid: str, group_id: str) -> dict | None:
    try:
        doc = pendingCartRepository.find_by_user_and_group(user_uid, group_id)
        if doc is None or _is_expired(doc):
            return None
        return _serialize(doc)
    except PyMongoError as err:
        raise HTTPException(status_code=500, detail=f"Error fetching pending cart: {err}")


def delete(user_uid: str, group_id: str) -> bool:
    try:
        pendingCartRepository.delete_by_user_and_group(user_uid, group_id)
        return True
    except PyMongoError as err:
        raise HTTPException(status_code=500, detail=f"Error deleting pending cart: {err}")
