"""The store's pickup code (design: plans/2026-11-21-delivery-handoff-design.md).

The store shows a 4-digit code and the rider types it. The code is created when a rider is
assigned, replaced when the rider changes, and shown only to members of the selling group while
the order waits for collection. Five wrong tries lock it for 15 minutes; fifteen in total retire
it, which leaves the rider's photo fallback as the only way and alerts the store.
"""
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, NamedTuple, Optional

from app.repositories import GroupRepository as groupRepository
from app.repositories import PickupCodeRepository as repo

logger = logging.getLogger(__name__)

TRIES_PER_WINDOW = 5
LOCK_MINUTES = 15
MAX_TOTAL_TRIES = 15
WAITING_STATUS = "WAITING_FOR_COLLECTION"


class VerifyResult(NamedTuple):
    status: str  # ok | wrong | locked | exhausted | none
    tries_left: Optional[int] = None
    retry_at: Optional[datetime] = None


def is_weak(code: str) -> bool:
    """All the same digit, or a straight run up or down (0000, 1111, 1234, 4321)."""
    digits = [int(c) for c in code]
    steps = {digits[i + 1] - digits[i] for i in range(len(digits) - 1)}
    return steps == {0} or steps == {1} or steps == {-1}


def generate_code() -> str:
    while True:
        code = f"{secrets.randbelow(10000):04d}"
        if not is_weak(code):
            return code


def assign_code(order_id: str) -> str:
    """Creates the order's code (or replaces it, clearing every counter) and returns it."""
    code = generate_code()
    repo.upsert_code(str(order_id), code)
    return code


def reset_code(order_id: str) -> str:
    """A new rider means a new code; the old one and its attempts stop counting."""
    return assign_code(order_id)


def has_code(order_id: str) -> bool:
    """False for orders assigned before codes existed: they keep the old no-code pickup."""
    return repo.find(str(order_id)) is not None


def delete_code(order_id: str) -> None:
    repo.delete(str(order_id))


def _user_in_group(user_uid: Optional[str], group_id: Optional[str]) -> bool:
    if not user_uid or not group_id:
        return False
    try:
        doc = groupRepository.find_users_by_group_id(str(group_id))
    except Exception:
        return False
    return bool(doc) and user_uid in (doc.get("users") or [])


def get_code_for_store(
    order_doc: Dict[str, Any],
    requesting_user_uid: Optional[str],
    _membership: Optional[Dict[str, bool]] = None,
) -> Optional[str]:
    """The code, only for a member of the selling group while the order waits for collection.
    `_membership` caches group lookups across the orders of one list."""
    status = order_doc.get("status")
    status = getattr(status, "value", status)
    if status != WAITING_STATUS:
        return None
    seller_group = (order_doc.get("offer") or {}).get("group_id")
    if _membership is not None and seller_group in _membership:
        is_member = _membership[seller_group]
    else:
        is_member = _user_in_group(requesting_user_uid, seller_group)
        if _membership is not None:
            _membership[seller_group] = is_member
    if not is_member:
        return None
    found = repo.find(str(order_doc.get("_id")))
    return (found or {}).get("code")


def _alert_store_guessing(order_id: str) -> None:
    """Tells the selling group someone tried to guess the code (alert wording lives in notification_fanout)."""
    from app.services import notification_fanout

    try:
        notification_fanout.fanout_pickup_code_guessing(order_id=order_id)
    except Exception as exc:  # an alert never changes the answer
        logger.warning("pickup code guessing alert failed for order %s: %s", order_id, type(exc).__name__)


def verify_code(order_id: str, code: str, now: Optional[datetime] = None) -> VerifyResult:
    now = now or datetime.now(timezone.utc)
    order_id = str(order_id)
    doc = repo.find(order_id)
    if not doc:
        return VerifyResult("none")
    if doc.get("retired") or doc.get("total_attempts", 0) >= MAX_TOTAL_TRIES:
        return VerifyResult("exhausted")
    locked_until = doc.get("locked_until")
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if locked_until is not None and now < locked_until:
        return VerifyResult("locked", retry_at=locked_until)

    if hmac.compare_digest(str(code or ""), str(doc.get("code") or "")):
        return VerifyResult("ok")

    updated = repo.record_wrong_attempt(order_id) or doc
    if updated.get("total_attempts", 0) >= MAX_TOTAL_TRIES:
        repo.retire(order_id)
        _alert_store_guessing(order_id)
        return VerifyResult("exhausted")
    if updated.get("attempts", 0) >= TRIES_PER_WINDOW:
        until = now + timedelta(minutes=LOCK_MINUTES)
        repo.lock_until(order_id, until)
        return VerifyResult("locked", retry_at=until)
    return VerifyResult("wrong", tries_left=TRIES_PER_WINDOW - updated.get("attempts", 0))
