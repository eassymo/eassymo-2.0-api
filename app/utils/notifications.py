"""Persist notifications in Mongo and publish inbox events (ADR-001)."""

from typing import Dict, Any

from app.schemas.Notification import Notification
from app.services import NotificationService as notificationService


def send_notification(notification: Notification, user_token: str = None) -> None:
    """user_token is accepted for backward compatibility but is not used."""
    notificationService.create(notification)


def send_notification_dict(notification: Dict[str, Any], user_token: str = None) -> None:
    notificationService.create(notification)


def send_notifications_batch(notifications: list) -> None:
    if notifications:
        notificationService.create_many(notifications)


def send_notification_legacy(notification: Notification) -> None:
    send_notification(notification)
