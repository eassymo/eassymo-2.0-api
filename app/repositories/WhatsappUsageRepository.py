from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Literal, Optional

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import database
from app.services.whatsapp_usage_math import effective_limit, percent_used, usage_state, window_end, window_expired

TIERS = "WhatsappTiers"
STORE_TIERS = "WhatsappStoreTiers"
SETTINGS = "WhatsappUsageSettings"
AUDIT = "WhatsappUsageAudit"
USAGE = "WhatsappStoreUsage"
EVENTS = "WhatsappUsageEvents"
GRANTS = "WhatsappCreditGrants"
REQUESTS = "WhatsappCreditRequests"

NORMAL_TIER_ID = "normal"
SETTINGS_ID = "global"

NORMAL_TIER_SEED = {
    "name": "Normal",
    "solicitudes_per_window": 50,
    "window_seconds": 28800,
    "token_ceiling_per_window": 300000,
    "burst_messages_per_minute": 30,
    "warn_at_percent": 80,
    "per_seller_cap_percent": None,
    "enforcement": "shadow",
    "active": True,
}

SETTINGS_DEFAULTS = {
    "enforcement_enabled": True,
    "shadow_all": True,
    "price_per_1k_prompt_tokens": 0.0,
    "price_per_1k_completion_tokens": 0.0,
    "error_alert_threshold": 5,
    "notice_cooldown_seconds": 1800,
}

_indexes_ready = False


# --- Shared helpers -------------------------------------------------------

def _tiers():
    return database.db[TIERS]


def _store_tiers():
    return database.db[STORE_TIERS]


def _settings():
    return database.db[SETTINGS]


def _audit():
    return database.db[AUDIT]


def _usage():
    return database.db[USAGE]


def _events():
    return database.db[EVENTS]


def _grants():
    return database.db[GRANTS]


def _requests():
    return database.db[REQUESTS]


def _groups():
    return database.db["groups"]


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
    _tiers().create_index([("tier_id", ASCENDING)], unique=True)
    _store_tiers().create_index([("group_id", ASCENDING)], unique=True)
    _audit().create_index([("at", DESCENDING)])
    _usage().create_index([("group_id", ASCENDING)], unique=True)
    _events().create_index([("event_id", ASCENDING)], unique=True)
    _events().create_index([("group_id", ASCENDING), ("created_at", DESCENDING)])
    _events().create_index([("uid", ASCENDING), ("created_at", DESCENDING)])
    _events().create_index([("created_at", ASCENDING)])
    _grants().create_index([("group_id", ASCENDING), ("window_start", ASCENDING)])
    _requests().create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    _requests().create_index([("group_id", ASCENDING), ("status", ASCENDING)])
    _indexes_ready = True


# --- Config: tiers --------------------------------------------------------

def seed_normal_tier() -> None:
    """Insert the `normal` tier if missing; never overwrites an edited one."""
    ensure_indexes()
    now = _now()
    _tiers().update_one(
        {"tier_id": NORMAL_TIER_ID},
        {"$setOnInsert": {**NORMAL_TIER_SEED, "tier_id": NORMAL_TIER_ID, "created_at": now, "updated_at": now}},
        upsert=True,
    )


def get_tier(tier_id: str) -> Optional[dict]:
    ensure_indexes()
    return _clean(_tiers().find_one({"tier_id": tier_id}))


def list_tiers() -> List[dict]:
    ensure_indexes()
    return [_clean(t) for t in _tiers().find({}).sort("created_at", ASCENDING)]


def create_tier(tier_id: str, doc: dict) -> dict:
    ensure_indexes()
    now = _now()
    _tiers().insert_one({**doc, "tier_id": tier_id, "created_at": now, "updated_at": now})
    return get_tier(tier_id)


def update_tier(tier_id: str, fields: dict) -> Optional[dict]:
    ensure_indexes()
    doc = _tiers().find_one_and_update(
        {"tier_id": tier_id},
        {"$set": {**fields, "updated_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    return _clean(doc)


# --- Config: store tier assignment ---------------------------------------

def count_stores_on_tier(tier_id: str) -> int:
    """Stores on a tier. `normal` also counts stores with no assignment row:
    total groups minus the stores assigned to any other tier."""
    ensure_indexes()
    if tier_id == NORMAL_TIER_ID:
        assigned_elsewhere = _store_tiers().count_documents({"tier_id": {"$ne": NORMAL_TIER_ID}})
        return max(_groups().count_documents({}) - assigned_elsewhere, 0)
    return _store_tiers().count_documents({"tier_id": tier_id})


def get_store_tier_id(group_id: str) -> str:
    """Assigned tier if it exists and is active, otherwise `normal`."""
    ensure_indexes()
    row = _store_tiers().find_one({"group_id": group_id})
    if not row or row.get("tier_id") in (None, NORMAL_TIER_ID):
        return NORMAL_TIER_ID
    tier = _tiers().find_one({"tier_id": row["tier_id"]})
    if not tier or not tier.get("active", True):
        return NORMAL_TIER_ID
    return row["tier_id"]


def assign_store_tier(group_id: str, tier_id: str, actor_uid: str) -> dict:
    ensure_indexes()
    now = _now()
    _store_tiers().update_one(
        {"group_id": group_id},
        {
            "$set": {"tier_id": tier_id, "assigned_by": actor_uid, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return _clean(_store_tiers().find_one({"group_id": group_id}))


# --- Config: global settings ---------------------------------------------

def get_settings() -> dict:
    ensure_indexes()
    stored = _clean(_settings().find_one({"_id": SETTINGS_ID})) or {}
    return {**SETTINGS_DEFAULTS, **stored}


def update_settings(fields: dict) -> dict:
    ensure_indexes()
    _settings().update_one(
        {"_id": SETTINGS_ID},
        {"$set": {**fields, "updated_at": _now()}},
        upsert=True,
    )
    return get_settings()


def incr_meter_errors() -> int:
    ensure_indexes()
    doc = _settings().find_one_and_update(
        {"_id": SETTINGS_ID},
        {"$inc": {"meter_errors": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int((doc or {}).get("meter_errors", 0))


# --- Config: audit --------------------------------------------------------

def write_audit(
    actor_uid: str,
    action: str,
    target: str,
    before: Optional[dict],
    after: Optional[dict],
    reason: Optional[str] = None,
) -> None:
    ensure_indexes()
    _audit().insert_one(
        {
            "actor_uid": actor_uid,
            "action": action,
            "target": target,
            "before": before,
            "after": after,
            "reason": reason,
            "at": _now(),
        }
    )


def list_audit(page: int, page_size: int) -> dict:
    ensure_indexes()
    total = _audit().count_documents({})
    cursor = _audit().find({}, {"_id": 0}).sort("at", DESCENDING).skip(max(page - 1, 0) * page_size).limit(page_size)
    return {"items": list(cursor), "total": total, "page": page, "page_size": page_size}


# --- Counters: per-store window usage ------------------------------------
# One doc per store in WhatsappStoreUsage. Every write that must not race is a
# single conditional update, so concurrent instances can never exceed a limit.

RESERVED_BURSTS_KEEP = 200
NOTICE_FIELDS = ("blocked_notified_at", "guard_notified_at")
_RESERVE_ATTEMPTS = 3

ReserveResult = Literal["reserved", "already_reserved", "blocked_quota", "blocked_tokens", "blocked_seller_cap"]


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """The Mongo client is not tz_aware: stored datetimes come back naive UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _clean_usage(doc: Optional[dict]) -> Optional[dict]:
    doc = _clean(doc)
    if doc is not None and "window_start" in doc:
        doc["window_start"] = _aware(doc["window_start"])
    return doc


def _fresh_window(tier_id: str, now: datetime) -> dict:
    return {
        "tier_id": tier_id,
        "window_start": now,
        "solicitudes_used": 0,
        "tokens_used": 0,
        "by_uid": {},
        "reserved_bursts": [],
        "warned_window": None,
    }


def get_usage(group_id: str) -> Optional[dict]:
    ensure_indexes()
    return _clean_usage(_usage().find_one({"group_id": group_id}))


def ensure_window(group_id: str, tier_id: str, window_seconds: int, now: datetime) -> dict:
    """Return the store's usage doc with an active window, creating it or
    starting a new window if the old one expired. The reset filters on the old
    `window_start`, so when two instances race only one resets."""
    ensure_indexes()
    col = _usage()
    doc = col.find_one({"group_id": group_id})
    if doc is None:
        try:
            col.update_one(
                {"group_id": group_id},
                {"$setOnInsert": {"group_id": group_id, **_fresh_window(tier_id, now)}},
                upsert=True,
            )
        except DuplicateKeyError:
            pass  # another instance created it first
        return _clean_usage(col.find_one({"group_id": group_id}))

    old_start = doc.get("window_start")
    if not window_expired(_aware(old_start), window_seconds, now):
        return _clean_usage(doc)

    reset = col.find_one_and_update(
        {"group_id": group_id, "window_start": old_start},
        {"$set": _fresh_window(tier_id, now)},
        return_document=ReturnDocument.AFTER,
    )
    if reset is None:  # another instance reset it first
        reset = col.find_one({"group_id": group_id})
    return _clean_usage(reset)


def _classify_miss(doc: dict, uid: str, burst_id: str, limit: int, token_ceiling: int, seller_cap: Optional[int]):
    if burst_id in (doc.get("reserved_bursts") or []):
        return "already_reserved"
    if doc.get("solicitudes_used", 0) >= limit:
        return "blocked_quota"
    if doc.get("tokens_used", 0) >= token_ceiling:
        return "blocked_tokens"
    if seller_cap is not None and (doc.get("by_uid") or {}).get(uid, 0) >= seller_cap:
        return "blocked_seller_cap"
    return None


def try_reserve(
    group_id: str,
    uid: str,
    burst_id: str,
    *,
    limit: int,
    token_ceiling: int,
    seller_cap: Optional[int],
    window_start: datetime,
) -> ReserveResult:
    """Charge one solicitud for `burst_id` in a single conditional update.
    On no match, read the doc to say why. If the window was reset under us
    (or a refund freed room between the update and the read), retry against
    the current window; after a few attempts raise so the caller fails open."""
    ensure_indexes()
    col = _usage()
    for _ in range(_RESERVE_ATTEMPTS):
        flt = {
            "group_id": group_id,
            "window_start": window_start,
            "reserved_bursts": {"$ne": burst_id},
            "solicitudes_used": {"$lt": limit},
            "tokens_used": {"$lt": token_ceiling},
        }
        if seller_cap is not None:
            # `$lt` would not match a seller with no key yet; `$not: {$gte}` does.
            flt[f"by_uid.{uid}"] = {"$not": {"$gte": seller_cap}}
        updated = col.find_one_and_update(
            flt,
            {
                "$inc": {"solicitudes_used": 1, f"by_uid.{uid}": 1},
                "$push": {"reserved_bursts": {"$each": [burst_id], "$slice": -RESERVED_BURSTS_KEEP}},
            },
        )
        if updated is not None:
            return "reserved"

        doc = col.find_one({"group_id": group_id})
        if doc is None:
            raise RuntimeError(f"whatsapp_usage: no usage doc for group {group_id}; call ensure_window first")
        reason = _classify_miss(doc, uid, burst_id, limit, token_ceiling, seller_cap)
        if reason is not None:
            return reason
        window_start = doc.get("window_start")
    raise RuntimeError(f"whatsapp_usage: reserve contention for group {group_id}")


def refund(group_id: str, uid: str, burst_id: str) -> None:
    """Undo a reservation. Matches only while the burst is still reserved in
    the current window, so a repeat refund or one after a reset is a no-op."""
    ensure_indexes()
    _usage().update_one(
        {"group_id": group_id, "reserved_bursts": burst_id},
        {
            "$inc": {"solicitudes_used": -1, f"by_uid.{uid}": -1},
            "$pull": {"reserved_bursts": burst_id},
        },
    )
    # A refunded burst is no solicitud: its ledger events stay (tokens were spent) but stop counting.
    _events().update_many({"burst_id": burst_id, "counted": True}, {"$set": {"counted": False}})


def add_tokens(group_id: str, tokens: int) -> None:
    if tokens <= 0:
        return
    ensure_indexes()
    _usage().update_one({"group_id": group_id}, {"$inc": {"tokens_used": int(tokens)}})


def claim_warning(group_id: str, window_start: datetime) -> bool:
    """True exactly once per window: the first caller to mark it."""
    ensure_indexes()
    result = _usage().update_one(
        {"group_id": group_id, "window_start": window_start, "warned_window": {"$ne": window_start}},
        {"$set": {"warned_window": window_start, "warned_at": _now()}},
    )
    return result.modified_count == 1


def claim_notice(group_id: str, field: str, cooldown_seconds: int, now: datetime) -> bool:
    """True if no notice of this kind was sent within the cooldown; stamps it.
    Upserts so the burst-guard notice works before the store has a window; when
    the doc exists but the cooldown holds, the upsert collides on group_id."""
    if field not in NOTICE_FIELDS:
        raise ValueError(f"unknown notice field: {field}")
    ensure_indexes()
    cutoff = now - timedelta(seconds=cooldown_seconds)
    try:
        result = _usage().update_one(
            {"group_id": group_id, "$or": [{field: None}, {field: {"$lte": cutoff}}]},
            {"$set": {field: now}},
            upsert=True,
        )
    except DuplicateKeyError:
        return False
    return result.modified_count == 1 or result.upserted_id is not None


# --- Ledger: append-only events ------------------------------------------

def insert_event(event: dict) -> bool:
    """Insert a ledger event; False if its `event_id` was already recorded."""
    ensure_indexes()
    doc = {**event}
    doc.setdefault("created_at", _now())
    try:
        _events().insert_one(doc)
    except DuplicateKeyError:
        return False
    return True


# --- Credit grants ------------------------------------------------------
# A grant belongs to one window (`window_start`). A grant made while no window
# is active is stored with `window_start=None` ("pending") and is bound to the
# next window when it starts (`bind_pending_grants`, called by the service).

def add_grant(group_id: str, amount: int, reason: str, granted_by: str, window_start: Optional[datetime]) -> dict:
    ensure_indexes()
    doc = {
        "group_id": group_id,
        "amount": int(amount),
        "reason": reason,
        "granted_by": granted_by,
        "window_start": window_start,
        "created_at": _now(),
    }
    _grants().insert_one(doc)
    return _clean(doc)


def sum_grants(group_id: str, window_start: Optional[datetime]) -> int:
    """Extra solicitudes for that window; `None` sums the pending grants."""
    ensure_indexes()
    rows = list(
        _grants().aggregate(
            [
                {"$match": {"group_id": group_id, "window_start": window_start}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
            ]
        )
    )
    return int(rows[0]["total"]) if rows else 0


def bind_pending_grants(group_id: str, window_start: datetime) -> int:
    ensure_indexes()
    result = _grants().update_many(
        {"group_id": group_id, "window_start": None},
        {"$set": {"window_start": window_start}},
    )
    return int(result.modified_count or 0)


def list_grants(group_id: str, window_start: Optional[datetime]) -> List[dict]:
    ensure_indexes()
    cursor = _grants().find({"group_id": group_id, "window_start": window_start}).sort("created_at", DESCENDING)
    return [_clean(g) for g in cursor]


# --- Credit requests ----------------------------------------------------

def _clean_request(doc: Optional[dict]) -> Optional[dict]:
    if doc is None:
        return None
    out = _clean(doc)
    if "_id" in doc:
        out = {"id": str(doc["_id"]), **out}
    return out


def create_credit_request(group_id: str, requested_by: str, note: Optional[str]) -> dict:
    ensure_indexes()
    doc = {
        "group_id": group_id,
        "requested_by": requested_by,
        "status": "pending",
        "note": note,
        "resolved_by": None,
        "resolved_at": None,
        "created_at": _now(),
    }
    result = _requests().insert_one(doc)
    return _clean_request({**doc, "_id": result.inserted_id})


def get_credit_request(request_id: str) -> Optional[dict]:
    ensure_indexes()
    try:
        oid = ObjectId(request_id)
    except (InvalidId, TypeError):
        return None
    return _clean_request(_requests().find_one({"_id": oid}))


def find_pending_credit_request(group_id: str) -> Optional[dict]:
    ensure_indexes()
    return _clean_request(_requests().find_one({"group_id": group_id, "status": "pending"}))


def list_credit_requests(status: Optional[str]) -> List[dict]:
    ensure_indexes()
    flt = {"status": status} if status else {}
    return [_clean_request(r) for r in _requests().find(flt).sort("created_at", DESCENDING)]


def resolve_credit_request(
    request_id: str, status: Literal["granted", "declined"], resolved_by: str
) -> Optional[dict]:
    """Resolve a pending request; None if the id is bad, unknown or already resolved."""
    ensure_indexes()
    try:
        oid = ObjectId(request_id)
    except (InvalidId, TypeError):
        return None
    doc = _requests().find_one_and_update(
        {"_id": oid, "status": "pending"},
        {"$set": {"status": status, "resolved_by": resolved_by, "resolved_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    return _clean_request(doc)


def reopen_credit_request(request_id: str, from_status: str) -> None:
    """Put a request we just resolved back to pending (the grant failed)."""
    ensure_indexes()
    try:
        oid = ObjectId(request_id)
    except (InvalidId, TypeError):
        return
    _requests().update_one(
        {"_id": oid, "status": from_status},
        {"$set": {"status": "pending", "resolved_by": None, "resolved_at": None}},
    )


# --- Aggregates (read the ledger) ------------------------------------------

REPORT_TIMEZONE = "America/Mexico_City"
TOP_STORES_LIMIT = 10

# A solicitud is a distinct burst with a counted, successful call: the one that
# reserved (retries and repairs are not counted; a refund un-counts the burst).
_SUMS = {
    "tokens": {"$sum": {"$add": [{"$ifNull": ["$prompt_tokens", 0]}, {"$ifNull": ["$completion_tokens", 0]}]}},
    "estimated_cost": {"$sum": {"$ifNull": ["$estimated_cost", 0]}},
}
_GROUP_SUMS = {
    "solicitudes_set": {
        "$addToSet": {
            "$cond": [{"$and": [{"$eq": ["$counted", True]}, {"$eq": ["$status", "ok"]}]}, "$burst_id", None]
        }
    },
    **_SUMS,
}
_COUNT_SOLICITUDES = {
    "$addFields": {"solicitudes": {"$size": {"$setDifference": ["$solicitudes_set", [None]]}}}
}


def _sums(row: dict) -> dict:
    return {
        "solicitudes": int(row.get("solicitudes", 0)),
        "tokens": int(row.get("tokens", 0)),
        "estimated_cost": float(row.get("estimated_cost", 0.0)),
    }


def aggregate_usage(since: datetime, until: datetime) -> dict:
    """Totals, per-day (Mexico City days) and top stores for [since, until)."""
    ensure_indexes()
    rows = list(
        _events().aggregate(
            [
                {"$match": {"created_at": {"$gte": since, "$lt": until}}},
                {
                    "$facet": {
                        "totals": [{"$group": {"_id": None, **_GROUP_SUMS}}, _COUNT_SOLICITUDES],
                        "by_day": [
                            {
                                "$group": {
                                    "_id": {
                                        "$dateToString": {
                                            "format": "%Y-%m-%d",
                                            "date": "$created_at",
                                            "timezone": REPORT_TIMEZONE,
                                        }
                                    },
                                    **_GROUP_SUMS,
                                }
                            },
                            _COUNT_SOLICITUDES,
                            {"$sort": {"_id": 1}},
                        ],
                        "top_stores": [
                            {"$group": {"_id": "$group_id", **_GROUP_SUMS}},
                            _COUNT_SOLICITUDES,
                            {"$sort": {"solicitudes": -1, "tokens": -1}},
                            {"$limit": TOP_STORES_LIMIT},
                        ],
                    }
                },
            ]
        )
    )
    facets = rows[0] if rows else {}
    totals = facets.get("totals") or []
    return {
        "totals": _sums(totals[0]) if totals else _sums({}),
        "by_day": [{"day": r["_id"], **_sums(r)} for r in facets.get("by_day") or []],
        "top_stores": [{"group_id": r["_id"], **_sums(r)} for r in facets.get("top_stores") or []],
    }


def iter_events(since: datetime, until: datetime) -> Iterator[dict]:
    ensure_indexes()
    cursor = _events().find({"created_at": {"$gte": since, "$lt": until}}, {"_id": 0}).sort("created_at", ASCENDING)
    for event in cursor:
        yield event


def by_seller(group_id: str) -> List[dict]:
    """Per-seller use of the store's latest window: solicitudes from the
    counter (`by_uid`), tokens from the ledger since `window_start`. The
    caller decides whether that window is still active."""
    ensure_indexes()
    usage = get_usage(group_id)
    if not usage or not usage.get("window_start"):
        return []
    solicitudes = {uid: int(n) for uid, n in (usage.get("by_uid") or {}).items()}
    rows = _events().aggregate(
        [
            {"$match": {"group_id": group_id, "created_at": {"$gte": usage["window_start"]}}},
            {"$group": {"_id": "$uid", "tokens": _SUMS["tokens"]}},
        ]
    )
    tokens = {r["_id"]: int(r.get("tokens", 0)) for r in rows if r.get("_id")}
    out = [
        {"uid": uid, "solicitudes": solicitudes.get(uid, 0), "tokens": tokens.get(uid, 0)}
        for uid in set(solicitudes) | set(tokens)
    ]
    out = [r for r in out if r["solicitudes"] > 0 or r["tokens"] > 0]
    return sorted(out, key=lambda r: (-r["solicitudes"], -r["tokens"], r["uid"]))


LIMIT_ALERT_CAP = 50


def list_active_usage(now: Optional[datetime] = None) -> List[dict]:
    """Stores whose CURRENT window is at or past the warn threshold or the
    limit, highest percent first, capped at LIMIT_ALERT_CAP. Independent of any
    date range. The state is the would-be state (as if enforced) and each row
    carries `enforcement_mode` ("enforce" | "shadow" | "off") so shadow-rollout
    data can be labelled."""
    ensure_indexes()
    now = now or _now()
    settings = get_settings()
    kill_switch = not settings.get("enforcement_enabled", True)
    shadow_all = bool(settings.get("shadow_all"))
    tiers = {t["tier_id"]: t for t in _tiers().find({}, {"_id": 0})}
    normal = tiers.get(NORMAL_TIER_ID) or {**NORMAL_TIER_SEED, "tier_id": NORMAL_TIER_ID}
    assigned = {r["group_id"]: r.get("tier_id") for r in _store_tiers().find({}, {"_id": 0})}
    docs = [_clean_usage(d) for d in _usage().find({"window_start": {"$ne": None}})]
    docs = [d for d in docs if d and not window_expired(_aware(d["window_start"]), _window_seconds(d, tiers, assigned, normal), now)]
    grants = {
        (r["_id"]["group_id"], _aware(r["_id"]["window_start"])): int(r["total"])
        for r in _grants().aggregate(
            [
                {"$match": {"window_start": {"$ne": None}, "group_id": {"$in": [d["group_id"] for d in docs]}}},
                {"$group": {"_id": {"group_id": "$group_id", "window_start": "$window_start"}, "total": {"$sum": "$amount"}}},
            ]
        )
    }
    out = []
    for d in docs:
        tier = _tier_for(d["group_id"], tiers, assigned, normal)
        if kill_switch:
            mode = "off"
        elif shadow_all or tier.get("enforcement", "shadow") != "enforce":
            mode = "shadow"
        else:
            mode = "enforce"
        limit = effective_limit(int(tier["solicitudes_per_window"]), grants.get((d["group_id"], _aware(d["window_start"])), 0))
        used, tokens = int(d.get("solicitudes_used", 0)), int(d.get("tokens_used", 0))
        ceiling = int(tier["token_ceiling_per_window"])
        percent = percent_used(used, limit, tokens, ceiling)
        state = usage_state(percent, int(tier.get("warn_at_percent", 80)), "enforce", used >= limit or tokens >= ceiling)  # would-be state
        if state in ("warning", "limit"):
            out.append(
                {
                    "group_id": d["group_id"], "tier_id": tier["tier_id"], "used": used, "limit": limit,
                    "percent": percent, "state": state, "enforcement_mode": mode,
                    "window_end": window_end(_aware(d["window_start"]), int(tier["window_seconds"])),
                }
            )
    out.sort(key=lambda r: (-r["percent"], r["group_id"]))
    return out[:LIMIT_ALERT_CAP]


def _tier_for(group_id: str, tiers: dict, assigned: dict, normal: dict) -> dict:
    tier = tiers.get(assigned.get(group_id) or NORMAL_TIER_ID)
    return tier if tier and tier.get("active", True) else normal


def _window_seconds(doc: dict, tiers: dict, assigned: dict, normal: dict) -> int:
    return int(_tier_for(doc["group_id"], tiers, assigned, normal)["window_seconds"])
