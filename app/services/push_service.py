"""Send FCM web push notifications to registered devices."""

import logging
from typing import Any, Dict, List, Optional

from firebase_admin import messaging
from firebase_admin.exceptions import FirebaseError

from app.repositories import PushSubscriptionRepository as pushSubscriptionRepository

logger = logging.getLogger(__name__)


def _stringify_data(data: Dict[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            import json

            result[str(key)] = json.dumps(value)
        else:
            result[str(key)] = str(value)
    return result


def send_push_to_uid(
    uid: str,
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> int:
    tokens = pushSubscriptionRepository.find_tokens_by_uid(uid)
    if not tokens:
        return 0

    payload_data = _stringify_data(data or {})
    invalid_tokens: List[str] = []
    sent = 0

    for token in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=payload_data,
                token=token,
                webpush=messaging.WebpushConfig(
                    notification=messaging.WebpushNotification(
                        title=title,
                        body=body,
                        icon="/icons/icon-192.png",
                    ),
                    fcm_options=messaging.WebpushFCMOptions(
                        link=payload_data.get("navigateToUrl") or "/notifications"
                    ),
                ),
            )
            messaging.send(message)
            sent += 1
        except FirebaseError as exc:
            error_code = getattr(exc, "code", "") or str(exc)
            if "registration-token-not-registered" in error_code or "invalid-argument" in error_code:
                invalid_tokens.append(token)
            else:
                logger.warning("FCM send failed for uid %s: %s", uid, exc)
        except Exception as exc:
            logger.warning("FCM send failed for uid %s: %s", uid, exc)

    if invalid_tokens:
        pushSubscriptionRepository.delete_tokens(invalid_tokens)

    return sent


def send_push_from_notification(notification: Dict[str, Any]) -> int:
    owner = notification.get("owner")
    message = notification.get("message") or "Tienes una nueva notificación"
    if not owner:
        return 0

    notification_type = notification.get("type")
    if hasattr(notification_type, "value"):
        notification_type = notification_type.value

    data = {
        "type": notification_type,
        "navigateToUrl": notification.get("navigateToUrl") or "/notifications",
        "uid": notification.get("uid") or "",
        "ownerGroup": notification.get("ownerGroup") or "",
        "owner": str(owner),
    }

    return send_push_to_uid(
        str(owner),
        title="Eassymo",
        body=str(message),
        data=data,
    )
