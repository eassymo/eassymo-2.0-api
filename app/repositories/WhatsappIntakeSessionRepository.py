from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pymongo import ReturnDocument

from app.config import database

COLLECTION = "WhatsappIntakeSessions"

STATUS_COLLECTING = "collecting"
STATUS_FLUSHING = "flushing"

MAX_MESSAGES = 20
MAX_CHARS = 8000


def _col():
    return database.db[COLLECTION]


def get_by_phone(from_number: str) -> Optional[dict]:
    return _col().find_one({"from_number": from_number})


def open_session(
    from_number: str,
    *,
    group_id: str,
    creator_uid: Optional[str],
    group_name: Optional[str] = None,
) -> dict:
    now = datetime.now(timezone.utc)
    doc = {
        "from_number": from_number,
        "status": STATUS_COLLECTING,
        "group_id": group_id,
        "creator_uid": creator_uid,
        "group_name": group_name,
        "messages": [],
        "generation": 1,
        "flush_at": None,
        "started_at": now,
        "updated_at": now,
    }
    _col().update_one(
        {"from_number": from_number},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return get_by_phone(from_number) or doc


def ensure_collecting_session(
    from_number: str,
    *,
    group_id: str,
    creator_uid: Optional[str],
    group_name: Optional[str] = None,
) -> dict:
    """Reuse an in-flight collecting session instead of wiping buffered messages."""
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"from_number": from_number},
        [
            {
                "$set": {
                    "from_number": from_number,
                    "status": STATUS_COLLECTING,
                    "group_id": group_id,
                    "creator_uid": creator_uid,
                    "group_name": group_name,
                    "updated_at": now,
                    "messages": {
                        "$cond": [
                            {"$eq": [{"$ifNull": ["$status", ""]}, STATUS_COLLECTING]},
                            {"$ifNull": ["$messages", []]},
                            [],
                        ]
                    },
                    "generation": {
                        "$cond": [
                            {"$eq": [{"$ifNull": ["$status", ""]}, STATUS_COLLECTING]},
                            {"$ifNull": ["$generation", 1]},
                            1,
                        ]
                    },
                    "flush_at": {
                        "$cond": [
                            {"$eq": [{"$ifNull": ["$status", ""]}, STATUS_COLLECTING]},
                            "$flush_at",
                            None,
                        ]
                    },
                    "started_at": {
                        "$cond": [
                            {"$eq": [{"$ifNull": ["$status", ""]}, STATUS_COLLECTING]},
                            {"$ifNull": ["$started_at", now]},
                            now,
                        ]
                    },
                    "created_at": {"$ifNull": ["$created_at", now]},
                }
            }
        ],
        upsert=True,
    )
    return get_by_phone(from_number) or {
        "from_number": from_number,
        "status": STATUS_COLLECTING,
        "group_id": group_id,
        "creator_uid": creator_uid,
        "group_name": group_name,
        "messages": [],
        "generation": 1,
        "flush_at": None,
        "started_at": now,
        "updated_at": now,
    }


def append_message(
    from_number: str,
    message: Dict[str, Any],
    *,
    quiet_seconds: int = 3,
) -> tuple[Optional[dict], bool, bool]:
    """
    Append a buffered message without bumping generation.

    Returns (session, should_auto_flush, schedule_debounce).
    schedule_debounce is True only when this append created the first content message.
    """
    now = datetime.now(timezone.utc)
    flush_at = now + timedelta(seconds=max(1, quiet_seconds))
    updated = _col().find_one_and_update(
        {"from_number": from_number, "status": STATUS_COLLECTING},
        [
            {
                "$set": {
                    "messages": {
                        "$concatArrays": [
                            {"$ifNull": ["$messages", []]},
                            [message],
                        ]
                    },
                    "updated_at": now,
                    "flush_at": {"$ifNull": ["$flush_at", flush_at]},
                }
            }
        ],
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        return None, False, False

    messages: List[dict] = list(updated.get("messages") or [])
    total_chars = sum(len((m.get("body") or "")) for m in messages)
    should_auto_flush = len(messages) >= MAX_MESSAGES or total_chars >= MAX_CHARS
    schedule_debounce = len(messages) == 1
    return updated, should_auto_flush, schedule_debounce


def bump_generation(from_number: str) -> Optional[dict]:
    """Invalidate pending debounce timers after explicit flush/cancel."""
    session = get_by_phone(from_number)
    if not session or session.get("status") != STATUS_COLLECTING:
        return session

    generation = int(session.get("generation") or 0) + 1
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"from_number": from_number, "status": STATUS_COLLECTING},
        {"$set": {"generation": generation, "updated_at": now}},
    )
    return get_by_phone(from_number)


def try_acquire_flush(from_number: str, generation: int) -> Optional[dict]:
    now = datetime.now(timezone.utc)
    return _col().find_one_and_update(
        {
            "from_number": from_number,
            "status": STATUS_COLLECTING,
            "generation": generation,
        },
        {
            "$set": {
                "status": STATUS_FLUSHING,
                "flush_token": uuid4().hex,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )


def find_due_collecting(now: datetime) -> List[dict]:
    """Collecting sessions whose quiet window has passed and a store is known."""
    return list(
        _col().find(
            {
                "status": STATUS_COLLECTING,
                "flush_at": {"$ne": None, "$lte": now},
                "group_id": {"$nin": [None, ""]},
            }
        )
    )


def reclaim_abandoned_flushes(
    now: datetime, *, min_age_seconds: Optional[int]
) -> int:
    """Return flushing sessions to collecting so a dead worker can be retried.

    min_age_seconds None reclaims every flush. A running process uses an age
    so it does not steal a flush that is still inside the model call.
    """
    query: Dict[str, Any] = {"status": STATUS_FLUSHING}
    if min_age_seconds is not None:
        query["updated_at"] = {
            "$lt": now - timedelta(seconds=max(0, min_age_seconds))
        }
    result = _col().update_many(
        query,
        {
            "$set": {
                "status": STATUS_COLLECTING,
                "flush_token": None,
                "flush_at": now,
                "updated_at": now,
            },
            "$inc": {"generation": 1},
        },
    )
    return int(result.modified_count)


def delete_session(from_number: str) -> None:
    _col().delete_one({"from_number": from_number})


def finish_session(from_number: str) -> None:
    delete_session(from_number)
