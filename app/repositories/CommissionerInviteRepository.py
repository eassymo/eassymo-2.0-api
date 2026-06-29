from typing import Any, Dict, List, Optional

from app.config import database
from bson import ObjectId


def insert(payload: Dict[str, Any]):
    return database.db["CommissionerInvites"].insert_one(payload)


def find(filters: Dict[str, Any]):
    return database.db["CommissionerInvites"].find(filters).sort("created_at", -1)


def find_by_id(invite_id: str):
    try:
        return database.db["CommissionerInvites"].find_one({"_id": ObjectId(invite_id)})
    except Exception:
        return None


def update_by_id(invite_id: str, payload: Dict[str, Any]):
    return database.db["CommissionerInvites"].find_one_and_update(
        {"_id": ObjectId(invite_id)},
        {"$set": payload},
        return_document=True,
    )


def find_recent_pair_any_status(
    commissioner_group_id: str, invited_group_id: str
):
    """Most recent invite for this pair — used by UI to hide duplicate sends."""
    return database.db["CommissionerInvites"].find_one(
        {"commissioner_group_id": commissioner_group_id, "invited_group_id": invited_group_id},
        sort=[("created_at", -1)],
    )


def find_latest_accepted_invite(commissioner_group_id: str, invited_group_id: str):
    return database.db["CommissionerInvites"].find_one(
        {
            "commissioner_group_id": commissioner_group_id,
            "invited_group_id": invited_group_id,
            "status": "ACCEPTED",
        },
        sort=[("updated_at", -1)],
    )


def find_accepted_invited_group_ids_for_commissioners(
    commissioner_group_ids: List[str],
) -> List[str]:
    """Distinct invited_group_id for ACCEPTED invites where commissioner is in the given list."""
    ids = [str(x).strip() for x in commissioner_group_ids if x and str(x).strip()]
    if not ids:
        return []
    seen: set[str] = set()
    for doc in database.db["CommissionerInvites"].find(
        {"commissioner_group_id": {"$in": ids}, "status": "ACCEPTED"},
        {"invited_group_id": 1},
    ):
        ig = doc.get("invited_group_id")
        if ig is None:
            continue
        seen.add(str(ig))
    return list(seen)
