from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import database

COLLECTION = "WhatsappPendingAssociations"


def _col():
    return database.db[COLLECTION]


def get_by_phone(from_number: str) -> Optional[dict]:
    return _col().find_one({"from_number": from_number})


def upsert_pending(
    from_number: str,
    candidates: List[Dict[str, str]],
    inbound_id: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"from_number": from_number},
        {
            "$set": {
                "from_number": from_number,
                "candidates": candidates,
                "last_inbound_id": inbound_id,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


def set_selected_store(from_number: str, group_id: str, creator_uid: Optional[str]) -> None:
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"from_number": from_number},
        {
            "$set": {
                "selected_group_id": group_id,
                "creator_uid": creator_uid,
                "updated_at": now,
            }
        },
    )


def clear_selected_store(from_number: str) -> None:
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"from_number": from_number},
        {
            "$unset": {"selected_group_id": ""},
            "$set": {"updated_at": now},
        },
    )


def clear(from_number: str) -> None:
    _col().delete_one({"from_number": from_number})
