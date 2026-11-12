from datetime import datetime, timezone
from typing import List, Optional

from pymongo import ASCENDING

from app.config import database
from app.utils.phone_normalize import phone_lookup_variants

COLLECTION = "WhatsappLinks"

_indexes_ready = False


def _col():
    return database.db[COLLECTION]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready or database.db is None:
        return
    _col().create_index([("uid", ASCENDING), ("group_id", ASCENDING)], unique=True)
    _col().create_index([("phone", ASCENDING)])
    _indexes_ready = True


def find(uid: str, group_id: str) -> Optional[dict]:
    ensure_indexes()
    return _col().find_one({"uid": uid, "group_id": group_id})


def find_any_by_phone(phone: str) -> List[dict]:
    ensure_indexes()
    return list(_col().find({"phone": {"$in": phone_lookup_variants(phone)}}))


def list_by_uid(uid: str) -> List[dict]:
    ensure_indexes()
    return list(_col().find({"uid": uid}))


def upsert(uid: str, group_id: str, phone: str, verified_at: datetime) -> dict:
    """Create or refresh a link. An existing status is never changed."""
    ensure_indexes()
    now = _now()
    _col().update_one(
        {"uid": uid, "group_id": group_id},
        {
            "$set": {"phone": phone, "verified_at": verified_at, "updated_at": now},
            "$setOnInsert": {"status": "active", "created_at": now},
        },
        upsert=True,
    )
    return _col().find_one({"uid": uid, "group_id": group_id})


def insert_if_absent(uid: str, group_id: str, phone: str, verified_at: datetime) -> bool:
    ensure_indexes()
    now = _now()
    result = _col().update_one(
        {"uid": uid, "group_id": group_id},
        {
            "$setOnInsert": {
                "phone": phone,
                "verified_at": verified_at,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return result.upserted_id is not None


def set_status(uid: str, group_id: str, status: str, by: Optional[str]) -> bool:
    ensure_indexes()
    now = _now()
    fields = {"status": status, "updated_at": now}
    if status == "disabled":
        fields["disabled_by"] = by
        fields["disabled_at"] = now
    else:
        fields["disabled_by"] = None
        fields["disabled_at"] = None
    result = _col().update_one({"uid": uid, "group_id": group_id}, {"$set": fields})
    return result.matched_count > 0
