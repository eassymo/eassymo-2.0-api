"""Publish ephemeral realtime events to Firebase RTDB (Admin SDK only).

Mongo remains source of truth. Failures here are logged and must not fail the
caller's Mongo transaction — see ADR-001.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Literal
from uuid import uuid4

from app.utils.firebase_admin import get_database_reference

logger = logging.getLogger(__name__)

ChatEntityType = Literal["request", "order"]

_FORBIDDEN_PATH_CHARS = set("./#$[]")


def _new_event_id() -> str:
    return str(uuid4())


def _server_timestamp() -> Dict[str, str]:
    return {"sv": "timestamp"}


def _safe_segment(name: str, value: str) -> str | None:
    normalized = value.strip()
    if not normalized or any(char in normalized for char in _FORBIDDEN_PATH_CHARS):
        logger.warning("%s skipped: invalid RTDB path segment %r", name, value)
        return None
    return normalized


def _safe_publish(action: str, fn) -> bool:
    try:
        fn()
        return True
    except Exception as exc:
        logger.warning("RTDB %s failed: %s", action, exc, exc_info=True)
        return False


def publish_inbox_event(uid: str, payload: Dict[str, Any]) -> str | None:
    """Signal a new inbox item for ``uid``. Returns event id or None on failure."""
    safe_uid = _safe_segment("publish_inbox_event uid", uid or "")
    if not safe_uid:
        return None

    event_id = _new_event_id()
    path = f"events/inbox/{safe_uid}/{event_id}"
    body = {
        **payload,
        "eventId": event_id,
        "eventType": payload.get("eventType", "notification.created"),
        "at": _server_timestamp(),
    }

    def _write():
        get_database_reference(path).set(body)

    if not _safe_publish(f"publish_inbox_event uid={safe_uid}", _write):
        return None
    return event_id


def publish_chat_event(
    entity_type: ChatEntityType,
    entity_id: str,
    payload: Dict[str, Any],
) -> str | None:
    """Signal a new chat message for ``entity_type`` / ``entity_id``."""
    if entity_type not in ("request", "order"):
        logger.warning("publish_chat_event skipped: invalid entity_type=%s", entity_type)
        return None

    safe_entity_id = _safe_segment("publish_chat_event entity_id", entity_id or "")
    if not safe_entity_id:
        return None

    event_id = _new_event_id()
    path = f"events/chat/{entity_type}/{safe_entity_id}/{event_id}"
    body = {
        **payload,
        "eventId": event_id,
        "eventType": payload.get("eventType", "message.created"),
        "at": _server_timestamp(),
    }

    def _write():
        get_database_reference(path).set(body)

    if not _safe_publish(
        f"publish_chat_event {entity_type}/{safe_entity_id}",
        _write,
    ):
        return None
    return event_id


def grant_chat_acl(
    entity_type: ChatEntityType,
    entity_id: str,
    uids: Iterable[str],
) -> bool:
    """Grant read/subscribe access for chat events and presence. Returns True on success."""
    if entity_type not in ("request", "order"):
        logger.warning("grant_chat_acl skipped: invalid entity_type=%s", entity_type)
        return False

    safe_entity_id = _safe_segment("grant_chat_acl entity_id", entity_id or "")
    if not safe_entity_id:
        return False

    unique_uids: set[str] = set()
    for uid in uids:
        safe_uid = _safe_segment("grant_chat_acl uid", str(uid) if uid is not None else "")
        if safe_uid:
            unique_uids.add(safe_uid)

    if not unique_uids:
        return False

    def _write():
        updates: Dict[str, bool] = {
            f"acl/chats/{entity_type}/{safe_entity_id}/{uid}": True for uid in unique_uids
        }
        get_database_reference("/").update(updates)

    return _safe_publish(
        f"grant_chat_acl {entity_type}/{safe_entity_id} uids={len(unique_uids)}",
        _write,
    )
