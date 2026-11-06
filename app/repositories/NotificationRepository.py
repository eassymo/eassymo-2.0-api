from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.config import database
from app.utils.datetime_utils import serialize_datetime, utc_timestamp_ms

COLLECTION = "notifications"
db = database.db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_indexes() -> None:
    if db is None:
        return
    db[COLLECTION].create_index([("owner", ASCENDING), ("ownerGroup", ASCENDING), ("createdAt", DESCENDING)])
    db[COLLECTION].create_index([("owner", ASCENDING), ("read", ASCENDING)])
    db[COLLECTION].create_index([("uid", ASCENDING)], unique=True, sparse=True)


def insert(doc: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    payload = {**doc, "createdAt": doc.get("createdAt") or now}
    result = db[COLLECTION].insert_one(payload)
    payload["_id"] = str(result.inserted_id)
    return payload


def insert_many(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not docs:
        return []
    now = _now()
    payloads = [{**doc, "createdAt": doc.get("createdAt") or now} for doc in docs]
    result = db[COLLECTION].insert_many(payloads)
    for idx, inserted_id in enumerate(result.inserted_ids):
        payloads[idx]["_id"] = str(inserted_id)
    return payloads


def find_for_user(
    *,
    owner: str,
    owner_group: str,
    callcenter_only: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"owner": owner, "ownerGroup": owner_group}
    if callcenter_only is True:
        query["callcenterId"] = {"$exists": True, "$ne": None}
    elif callcenter_only is False:
        query["$or"] = [{"callcenterId": {"$exists": False}}, {"callcenterId": None}]

    cursor = (
        db[COLLECTION]
        .find(query)
        .sort("createdAt", DESCENDING)
        .skip(max(skip, 0))
        .limit(min(max(limit, 1), 500))
    )
    return [_serialize(doc) for doc in cursor]


def find_by_id(notification_id: str, owner: str) -> Optional[Dict[str, Any]]:
    try:
        oid = ObjectId(notification_id)
    except Exception:
        return None
    doc = db[COLLECTION].find_one({"_id": oid, "owner": owner})
    return _serialize(doc) if doc else None


def mark_read(notification_id: str, owner: str) -> bool:
    try:
        oid = ObjectId(notification_id)
    except Exception:
        return False
    result = db[COLLECTION].update_one(
        {"_id": oid, "owner": owner},
        {"$set": {"read": True, "updatedAt": _now()}},
    )
    return result.modified_count > 0


def mark_all_read(owner: str, owner_group: str, callcenter_only: Optional[bool] = None) -> int:
    query: Dict[str, Any] = {"owner": owner, "ownerGroup": owner_group, "read": False}
    if callcenter_only is True:
        query["callcenterId"] = {"$exists": True, "$ne": None}
    elif callcenter_only is False:
        query["$or"] = [{"callcenterId": {"$exists": False}}, {"callcenterId": None}]

    result = db[COLLECTION].update_many(
        query,
        {"$set": {"read": True, "updatedAt": _now()}},
    )
    return result.modified_count


def _utc_timestamp_ms(value: datetime) -> int:
    return utc_timestamp_ms(value)


def _serialize(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    out = dict(doc)
    if "_id" in out:
        out["id"] = str(out.pop("_id"))
    if isinstance(out.get("createdAt"), datetime):
        out["timestamp"] = _utc_timestamp_ms(out["createdAt"])
    return out


try:
    ensure_indexes()
except Exception:
    pass
