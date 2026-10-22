from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING

from app.config import database

COLLECTION = "WhatsappIntakeVerifications"

_indexes_ready = False


def _col():
    return database.db[COLLECTION]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready or database.db is None:
        return
    _col().create_index([("uid", ASCENDING), ("status", ASCENDING)])
    _col().create_index([("token_hash", ASCENDING)], unique=True)
    _col().create_index([("uid", ASCENDING), ("created_at", ASCENDING)])
    _indexes_ready = True


def find_open_by_uid(uid: str) -> Optional[dict]:
    ensure_indexes()
    return _col().find_one(
        {
            "uid": uid,
            "status": "open",
            "consumed_at": None,
            "expires_at": {"$gt": _now()},
        },
        sort=[("created_at", -1)],
    )


def count_distinct_phones(uid: str, since: datetime) -> int:
    keys = set()
    for doc in list_starts_since(uid, since):
        digits = "".join(ch for ch in (doc.get("phone") or "") if ch.isdigit())
        keys.add(digits[-10:] if len(digits) >= 10 else digits)
    keys.discard("")
    return len(keys)


def list_starts_since(uid: str, since: datetime) -> List[dict]:
    ensure_indexes()
    return list(
        _col().find(
            {"uid": uid, "created_at": {"$gte": since}},
            {"phone": 1, "created_at": 1},
        )
    )


def supersede_open(uid: str) -> None:
    now = _now()
    _col().update_many(
        {"uid": uid, "status": "open"},
        {"$set": {"status": "superseded", "superseded_at": now, "updated_at": now}},
    )


def insert(doc: Dict[str, Any]) -> dict:
    ensure_indexes()
    now = _now()
    payload = {**doc, "updated_at": doc.get("updated_at") or now}
    _col().insert_one(payload)
    return payload


def find_by_token_hash(token_hash: str) -> Optional[dict]:
    ensure_indexes()
    return _col().find_one({"token_hash": token_hash})


def mark_consumed(token_hash: str) -> None:
    now = _now()
    _col().update_one(
        {"token_hash": token_hash},
        {"$set": {"consumed_at": now, "status": "consumed", "updated_at": now}},
    )


def mark_failed(token_hash: str) -> None:
    now = _now()
    _col().update_one(
        {"token_hash": token_hash},
        {"$set": {"status": "failed", "failed_at": now, "updated_at": now}},
    )
