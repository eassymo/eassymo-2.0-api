from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING

from app.config import database

COLLECTION = "push_subscriptions"
db = database.db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_indexes() -> None:
    if db is None:
        return
    db[COLLECTION].create_index([("token", ASCENDING)], unique=True)
    db[COLLECTION].create_index([("uid", ASCENDING)])


def upsert_subscription(
    uid: str,
    token: str,
    user_agent: Optional[str] = None,
    group_id: Optional[str] = None,
) -> Dict[str, Any]:
    now = _now()
    doc = {
        "uid": uid,
        "token": token,
        "userAgent": user_agent,
        "groupId": group_id,
        "lastSeenAt": now,
    }
    db[COLLECTION].update_one(
        {"token": token},
        {
            "$set": doc,
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )
    return doc


def delete_subscription(uid: str, token: Optional[str] = None) -> int:
    query: Dict[str, Any] = {"uid": uid}
    if token:
        query["token"] = token
    result = db[COLLECTION].delete_many(query)
    return result.deleted_count


def find_tokens_by_uid(uid: str) -> List[str]:
    cursor = db[COLLECTION].find({"uid": uid}, {"token": 1})
    return [doc["token"] for doc in cursor if doc.get("token")]


def delete_tokens(tokens: List[str]) -> int:
    if not tokens:
        return 0
    result = db[COLLECTION].delete_many({"token": {"$in": tokens}})
    return result.deleted_count


try:
    ensure_indexes()
except Exception:
    pass
