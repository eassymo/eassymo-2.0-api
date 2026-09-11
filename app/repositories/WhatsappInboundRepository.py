from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.config import database

COLLECTION = "WhatsappInboundMessages"


def _col():
    return database.db[COLLECTION]


def insert_if_new(message: Dict[str, Any]) -> Tuple[Optional[str], bool]:
    """
    Persist an inbound message. Returns (document_id, created).
    Skips insert when MessageSid already exists (Twilio retry).
    """
    message_sid = message.get("message_sid")
    if not message_sid:
        raise ValueError("message_sid is required")

    now = datetime.now(timezone.utc)
    result = _col().update_one(
        {"message_sid": message_sid},
        {
            "$setOnInsert": {
                **message,
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    created = result.upserted_id is not None
    if created:
        return str(result.upserted_id), True

    existing = _col().find_one({"message_sid": message_sid}, {"_id": 1})
    doc_id = str(existing["_id"]) if existing else None
    return doc_id, False


def find_by_message_sid(message_sid: str) -> Optional[dict]:
    return _col().find_one({"message_sid": message_sid})


def update_fields(message_sid: str, fields: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"message_sid": message_sid},
        {"$set": {**fields, "updated_at": now}},
    )
