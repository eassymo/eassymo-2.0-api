from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId

from app.config import database

COLLECTION = "WhatsappInboundMessages"


def _col():
    return database.db[COLLECTION]


def ensure_indexes() -> None:
    _col().create_index([("created_at", -1), ("from_number", 1)])
    _col().create_index([("folio_id", 1), ("created_at", 1)])
    _col().create_index([("burst_id", 1)])


def _serialize_doc(doc: dict) -> dict:
    out = dict(doc)
    out["_id"] = str(out["_id"])
    for key in ("created_at", "updated_at"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = value.isoformat()
    return out


def _build_list_query(
    *,
    from_number: Optional[str] = None,
    extraction_status: Optional[str] = None,
    processing_status: Optional[str] = None,
    group_id: Optional[str] = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if from_number:
        query["from_number"] = from_number.strip()
    if extraction_status:
        query["extraction_status"] = extraction_status.strip()
    if processing_status:
        query["processing_status"] = processing_status.strip()
    if group_id:
        query["resolved_group_id"] = group_id.strip()
    return query


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


def find_latest_share_token(from_number: str) -> Optional[str]:
    if not from_number:
        return None
    doc = _col().find_one(
        {
            "from_number": from_number,
            "share_token": {"$exists": True, "$nin": [None, ""]},
        },
        sort=[("created_at", -1)],
    )
    return (doc or {}).get("share_token")


def update_fields(message_sid: str, fields: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"message_sid": message_sid},
        {"$set": {**fields, "updated_at": now}},
    )


def insert_outbound(message: Dict[str, Any]) -> str:
    """Persist an outbound bot message (not from Twilio webhook)."""
    message_sid = message.get("message_sid")
    if not message_sid:
        raise ValueError("message_sid is required")

    now = datetime.now(timezone.utc)
    doc = {
        **message,
        "direction": message.get("direction") or "outbound",
        "created_at": now,
        "updated_at": now,
    }
    _col().insert_one(doc)
    inserted = _col().find_one({"message_sid": message_sid}, {"_id": 1})
    return str(inserted["_id"]) if inserted else message_sid


def link_burst_to_folio(
    burst_id: str,
    folio_id: str,
    share_token: str,
    *,
    processing_status: str,
    extraction_status: str = "ready",
    extraction_proposal: Optional[Dict[str, Any]] = None,
) -> None:
    """Backfill folio linkage on every message in a flush burst (inbound + outbound)."""
    if not burst_id:
        return
    now = datetime.now(timezone.utc)
    fields: Dict[str, Any] = {
        "folio_id": folio_id,
        "share_token": share_token,
        "processing_status": processing_status,
        "extraction_status": extraction_status,
        "updated_at": now,
    }
    if extraction_proposal is not None:
        fields["extraction_proposal"] = extraction_proposal
    _col().update_many({"burst_id": burst_id}, {"$set": fields})


def list_by_folio_id(folio_id: str) -> List[dict]:
    ensure_indexes()
    cursor = (
        _col()
        .find({"folio_id": folio_id})
        .sort("created_at", 1)
    )
    return [_serialize_doc(doc) for doc in cursor]


def list_messages(
    page: int = 1,
    page_size: int = 20,
    *,
    from_number: Optional[str] = None,
    extraction_status: Optional[str] = None,
    processing_status: Optional[str] = None,
    group_id: Optional[str] = None,
) -> Dict[str, Any]:
    ensure_indexes()
    query = _build_list_query(
        from_number=from_number,
        extraction_status=extraction_status,
        processing_status=processing_status,
        group_id=group_id,
    )
    skip = max(page - 1, 0) * page_size
    total = _col().count_documents(query)
    cursor = (
        _col()
        .find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(page_size)
    )
    items: List[dict] = [_serialize_doc(doc) for doc in cursor]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 1),
    }


def find_by_id(document_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(document_id)
    except (InvalidId, TypeError):
        return None
    doc = _col().find_one({"_id": oid})
    if not doc:
        return None
    return _serialize_doc(doc)
