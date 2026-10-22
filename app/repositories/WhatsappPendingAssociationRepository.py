from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.config import database

COLLECTION = "WhatsappPendingAssociations"
DEFAULT_PROMPT_COOLDOWN_SECONDS = 60


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
                "last_inbound_at": now,
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
                "last_inbound_at": now,
                "updated_at": now,
            }
        },
    )


def touch_last_inbound(from_number: str) -> None:
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"from_number": from_number},
        {"$set": {"last_inbound_at": now, "updated_at": now}},
    )


def clear_selected_store(from_number: str) -> bool:
    """Clear sticky store. Returns True only for the caller that actually unset it."""
    now = datetime.now(timezone.utc)
    result = _col().update_one(
        {
            "from_number": from_number,
            "selected_group_id": {"$exists": True, "$nin": [None, ""]},
        },
        {
            "$unset": {"selected_group_id": ""},
            "$set": {"updated_at": now},
        },
    )
    return result.modified_count > 0


def claim_identity_prompt(
    from_number: str,
    *,
    cooldown_seconds: int = DEFAULT_PROMPT_COOLDOWN_SECONDS,
    force: bool = False,
) -> bool:
    """Atomically claim the next identity prompt for this phone.

    Returns True only for the caller that should send the WhatsApp list/link message.
    Concurrent burst messages and retries inside the cooldown return False.
    """
    now = datetime.now(timezone.utc)
    if force:
        result = _col().update_one(
            {"from_number": from_number},
            {"$set": {"identity_prompted_at": now, "updated_at": now}},
        )
        return result.matched_count > 0 or result.modified_count > 0

    cutoff = now - timedelta(seconds=max(1, cooldown_seconds))
    result = _col().update_one(
        {
            "from_number": from_number,
            "$or": [
                {"identity_prompted_at": {"$exists": False}},
                {"identity_prompted_at": None},
                {"identity_prompted_at": {"$lt": cutoff}},
            ],
        },
        {"$set": {"identity_prompted_at": now, "updated_at": now}},
    )
    return result.modified_count > 0


def set_last_share_token(from_number: str, share_token: str) -> None:
    if not from_number or not share_token:
        return
    now = datetime.now(timezone.utc)
    _col().update_one(
        {"from_number": from_number},
        {
            "$set": {
                "from_number": from_number,
                "last_share_token": share_token,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


def get_last_share_token(from_number: str) -> Optional[str]:
    doc = get_by_phone(from_number) or {}
    token = doc.get("last_share_token")
    return str(token) if token else None


def clear(from_number: str) -> None:
    _col().delete_one({"from_number": from_number})
