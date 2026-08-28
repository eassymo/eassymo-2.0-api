"""Write notifications to Firebase RTDB via Admin SDK (no user tokens in URLs)."""

from uuid import uuid4
from typing import Dict, Any

from app.schemas.Notification import Notification
from app.utils.firebase_admin import get_database_reference
from app.services import push_service


def _push_notification(path: str, notification_data: Dict[str, Any], owner: str) -> None:
    uid = str(uuid4())
    notifications_ref = get_database_reference(path)
    payload = {
        **notification_data,
        "uid": uid,
        "timestamp": {"sv": "timestamp"},
    }
    notifications_ref.push(payload)
    try:
        push_service.send_push_from_notification({**notification_data, "uid": uid})
    except Exception:
        pass


def send_notification(notification: Notification, user_token: str = None) -> None:
    """
    Send a notification to Firebase Realtime Database using the Admin SDK.
    user_token is accepted for backward compatibility but is not used for auth.
    """
    notification_dict = notification.model_dump()
    if hasattr(notification_dict.get("type"), "value"):
        notification_dict["type"] = notification_dict["type"].value

    path = f"notifications/{notification.ownerGroup}/{notification.owner}"
    _push_notification(path, notification_dict, notification.owner)


def send_notification_dict(notification: Dict[str, Any], user_token: str = None) -> None:
    """
    Send a notification dictionary to Firebase Realtime Database using the Admin SDK.
    user_token is accepted for backward compatibility but is not used for auth.
    """
    path = f"notifications/{notification['ownerGroup']}/{notification['owner']}"
    _push_notification(path, notification, notification["owner"])


def send_notification_legacy(notification: Notification) -> None:
    """Deprecated alias — use send_notification."""
    send_notification(notification)
