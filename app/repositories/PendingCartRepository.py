from app.config import database
from datetime import datetime, timezone


def _filter(user_uid: str, group_id: str) -> dict:
    return {"user_uid": user_uid, "group_id": group_id}


def upsert(user_uid: str, group_id: str, payload: dict) -> dict:
    now = datetime.now(timezone.utc)
    payload["updated_at"] = now
    payload["saved_at"] = now

    database.db["pending_carts"].update_one(
        _filter(user_uid, group_id),
        {"$set": payload, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return database.db["pending_carts"].find_one(_filter(user_uid, group_id))


def find_by_user_and_group(user_uid: str, group_id: str) -> dict | None:
    return database.db["pending_carts"].find_one(_filter(user_uid, group_id))


def find_by_id(cart_id) -> dict | None:
    from bson import ObjectId
    try:
        return database.db["pending_carts"].find_one({"_id": ObjectId(cart_id)})
    except Exception:
        return None


def delete_by_user_and_group(user_uid: str, group_id: str) -> int:
    result = database.db["pending_carts"].delete_one(_filter(user_uid, group_id))
    return result.deleted_count
