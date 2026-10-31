"""Persist notifications in Mongo and publish inbox events."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.repositories import NotificationRepository as notificationRepository
from app.schemas.Notification import Notification
from app.services import push_service, realtime_bus


def _normalize_type(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _to_document(notification: Notification | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(notification, Notification):
        data = notification.model_dump()
    else:
        data = dict(notification)

    notif_type = _normalize_type(data.get("type"))
    uid = data.get("uid") or str(uuid4())

    return {
        "type": notif_type,
        "message": data.get("message") or "",
        "ownerGroup": data.get("ownerGroup") or "",
        "owner": data.get("owner") or "",
        "metaData": data.get("metaData") or {},
        "visibleRoles": data.get("visibleRoles"),
        "uid": uid,
        "navigateToUrl": data.get("navigateToUrl"),
        "read": bool(data.get("read", False)),
        "callcenterId": data.get("callcenterId"),
        "callcenterName": data.get("callcenterName"),
    }


def _publish_saved(doc: Dict[str, Any]) -> None:
    owner = doc.get("owner")
    if not owner:
        return

    realtime_bus.publish_inbox_event(
        str(owner),
        {
            "notificationId": doc.get("id") or doc.get("_id"),
            "uid": doc.get("uid"),
            "type": doc.get("type"),
            "ownerGroup": doc.get("ownerGroup"),
            "callcenterId": doc.get("callcenterId"),
        },
    )

    try:
        push_service.send_push_from_notification(doc)
    except Exception:
        pass


def create(notification: Notification | Dict[str, Any]) -> Dict[str, Any]:
    doc = _to_document(notification)
    saved = notificationRepository.insert(doc)
    _publish_saved(saved)
    return saved


def create_without_side_effects(notification: Notification | Dict[str, Any]) -> Dict[str, Any]:
    """Persist only — used by legacy RTDB migration (no inbox event / push)."""
    doc = _to_document(notification)
    return notificationRepository.insert(doc)


def create_many(notifications: List[Notification | Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not notifications:
        return []
    docs = [_to_document(item) for item in notifications]
    saved = notificationRepository.insert_many(docs)
    for doc in saved:
        _publish_saved(doc)
    return saved


def list_for_user(
    *,
    owner: str,
    owner_group: str,
    callcenter_only: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return notificationRepository.find_for_user(
        owner=owner,
        owner_group=owner_group,
        callcenter_only=callcenter_only,
        skip=skip,
        limit=limit,
    )


def mark_read(notification_id: str, owner: str) -> bool:
    return notificationRepository.mark_read(notification_id, owner)


def mark_all_read(
    owner: str,
    owner_group: str,
    callcenter_only: Optional[bool] = None,
) -> int:
    return notificationRepository.mark_all_read(
        owner=owner,
        owner_group=owner_group,
        callcenter_only=callcenter_only,
    )
