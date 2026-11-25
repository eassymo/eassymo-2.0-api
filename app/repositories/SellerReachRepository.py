"""Seller reach cap: settings, per-store overrides, daily wide-request counters and audit events.

`day` is a local calendar day string (America/Mexico_City), computed by the caller.
Every counter write that must not race is a single conditional update.
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import database

SETTINGS = "SellerReachSettings"
OVERRIDES = "SellerReachStoreOverrides"
USAGE = "SellerReachUsage"
EVENTS = "SellerReachEvents"

SETTINGS_ID = "global"
SETTINGS_DEFAULTS = {"wide_threshold": 50, "wide_per_day": 2, "capped_max": 20, "enforcement": "shadow"}

EVENT_KINDS = frozenset(
    {"wide_reserved", "wide_released", "capped", "refused", "would_block", "join_skipped", "settings_changed"}
)

ReserveResult = Literal["reserved", "already_reserved", "exhausted"]

_indexes_ready = False


def _settings():
    return database.db[SETTINGS]


def _overrides():
    return database.db[OVERRIDES]


def _usage():
    return database.db[USAGE]


def _events():
    return database.db[EVENTS]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(doc: Optional[dict]) -> Optional[dict]:
    if doc is None:
        return None
    return {k: v for k, v in doc.items() if k != "_id"}


def ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready or database.db is None:
        return
    _overrides().create_index([("group_id", ASCENDING)], unique=True)
    _usage().create_index([("group_id", ASCENDING), ("day", ASCENDING)], unique=True)
    _events().create_index([("created_at", DESCENDING)])
    _events().create_index([("group_id", ASCENDING), ("created_at", DESCENDING)])
    _indexes_ready = True


# --- Settings ------------------------------------------------------------

def get_settings() -> dict:
    ensure_indexes()
    stored = _clean(_settings().find_one({"_id": SETTINGS_ID})) or {}
    return {**SETTINGS_DEFAULTS, **stored}


def update_settings(fields: dict, actor_uid: str) -> dict:
    ensure_indexes()
    before = get_settings()
    _settings().update_one(
        {"_id": SETTINGS_ID},
        {"$set": {**fields, "updated_at": _now(), "updated_by": actor_uid}},
        upsert=True,
    )
    after = get_settings()
    write_event("settings_changed", "global", actor_uid=actor_uid, scope="global", before=before, after=after)
    return after


# --- Per-store overrides -------------------------------------------------

def get_override(group_id: str) -> Optional[dict]:
    ensure_indexes()
    return _clean(_overrides().find_one({"group_id": group_id}))


def list_overrides() -> list:
    ensure_indexes()
    return [_clean(d) for d in _overrides().find({}).sort("updated_at", DESCENDING)]


def set_override(group_id: str, fields: dict, actor_uid: str) -> dict:
    ensure_indexes()
    before = get_override(group_id)
    _overrides().update_one(
        {"group_id": group_id},
        {"$set": {**fields, "updated_at": _now(), "updated_by": actor_uid}},
        upsert=True,
    )
    after = get_override(group_id)
    write_event("settings_changed", group_id, actor_uid=actor_uid, scope="override", before=before, after=after)
    return after


def clear_override(group_id: str, actor_uid: str) -> None:
    ensure_indexes()
    before = get_override(group_id)
    _overrides().delete_one({"group_id": group_id})
    write_event("settings_changed", group_id, actor_uid=actor_uid, scope="override", before=before, after=None)


# --- Counters: wide requests per store per day ---------------------------

def get_usage(group_id: str, day: str) -> dict:
    ensure_indexes()
    doc = _clean(_usage().find_one({"group_id": group_id, "day": day}))
    if doc is None:
        return {"wide_used": 0, "wide_request_ids": []}
    return doc


def try_reserve_wide(group_id: str, day: str, request_id: str, limit: int) -> ReserveResult:
    """Take one wide slot for `request_id` in a single conditional update, so two
    concurrent callers can never exceed `limit`. Idempotent per request id."""
    ensure_indexes()
    col = _usage()
    try:
        col.update_one(
            {"group_id": group_id, "day": day},
            {"$setOnInsert": {"group_id": group_id, "day": day, "wide_used": 0, "wide_request_ids": [], "created_at": _now()}},
            upsert=True,
        )
    except DuplicateKeyError:
        pass  # another instance created it first
    updated = col.find_one_and_update(
        {"group_id": group_id, "day": day, "wide_request_ids": {"$ne": request_id}, "wide_used": {"$lt": limit}},
        {"$inc": {"wide_used": 1}, "$push": {"wide_request_ids": request_id}},
    )
    if updated is not None:
        return "reserved"
    doc = col.find_one({"group_id": group_id, "day": day}) or {}
    if request_id in (doc.get("wide_request_ids") or []):
        return "already_reserved"
    return "exhausted"


def release_wide(group_id: str, day: str, request_id: str) -> None:
    """Give a slot back. Matches only while the id is still reserved, so a repeat release is a no-op."""
    ensure_indexes()
    _usage().update_one(
        {"group_id": group_id, "day": day, "wide_request_ids": request_id},
        {"$inc": {"wide_used": -1}, "$pull": {"wide_request_ids": request_id}},
    )


# --- Audit events --------------------------------------------------------

def write_event(kind: str, group_id: str, **fields) -> None:
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown seller reach event kind: {kind}")
    ensure_indexes()
    _events().insert_one({**fields, "kind": kind, "group_id": group_id, "created_at": _now()})


def list_events(page: int, page_size: int, group_id: Optional[str] = None) -> dict:
    ensure_indexes()
    flt = {"group_id": group_id} if group_id else {}
    total = _events().count_documents(flt)
    cursor = (
        _events().find(flt, {"_id": 0}).sort("created_at", DESCENDING).skip(max(page - 1, 0) * page_size).limit(page_size)
    )
    return {"items": list(cursor), "total": total, "page": page, "page_size": page_size}
