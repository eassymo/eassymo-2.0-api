from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import database

COLLECTION = "WhatsappNumberVerifications"


def _col():
    return database.db[COLLECTION]


def insert(doc: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    doc.setdefault("created_at", now)
    doc.setdefault("updated_at", now)
    _col().insert_one(doc)


def find_by_token_hash(token_hash: str) -> Optional[dict]:
    return _col().find_one({"token_hash": token_hash})


def find_open_by_uid(uid: str) -> Optional[dict]:
    now = datetime.now(timezone.utc)
    return _col().find_one(
        {
            "uid": uid,
            "consumed_at": None,
            "expires_at": {"$gt": now},
        },
        sort=[("created_at", -1)],
    )


def supersede_open(uid: str) -> None:
    now = datetime.now(timezone.utc)
    _col().update_many(
        {"uid": uid, "consumed_at": None},
        {
            "$set": {
                "consumed_at": now,
                "superseded_at": now,
                "updated_at": now,
            }
        },
    )


def count_distinct_phones(uid: str, since: datetime) -> int:
    pipeline = [
        {"$match": {"uid": uid, "created_at": {"$gte": since}}},
        {"$group": {"_id": "$phone"}},
        {"$count": "total"},
    ]
    rows = list(_col().aggregate(pipeline))
    if not rows:
        return 0
    return int(rows[0].get("total") or 0)


def list_starts_since(uid: str, since: datetime) -> List[dict]:
    return list(
        _col()
        .find({"uid": uid, "created_at": {"$gte": since}}, {"phone": 1, "created_at": 1})
        .sort("created_at", 1)
    )


def mark_consumed(token_hash: str) -> None:
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"token_hash": token_hash},
        {"$set": {"consumed_at": now, "updated_at": now}},
    )
