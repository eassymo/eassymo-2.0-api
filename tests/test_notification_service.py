import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("app.config.database", MagicMock())

from app.services import NotificationService as notification_service


def test_create_publishes_inbox_event_and_push():
    saved = {
        "id": "mongo-1",
        "uid": "notif-uid-1",
        "owner": "user-1",
        "ownerGroup": "group-1",
        "type": "OFFER_CREATED",
        "message": "hello",
        "read": False,
    }

    with patch("app.services.NotificationService.notificationRepository.insert", return_value=saved) as insert, \
         patch("app.services.NotificationService.realtime_bus.publish_inbox_event") as publish, \
         patch("app.services.NotificationService.push_service.send_push_from_notification") as push:
        result = notification_service.create(
            {
                "type": "OFFER_CREATED",
                "message": "hello",
                "ownerGroup": "group-1",
                "owner": "user-1",
                "metaData": {},
                "read": False,
            }
        )

        assert result == saved
        insert.assert_called_once()
        publish.assert_called_once()
        push.assert_called_once()


def test_list_for_user_scopes_owner():
    with patch("app.services.NotificationService.notificationRepository.find_for_user", return_value=[]) as find:
        notification_service.list_for_user(owner="u1", owner_group="g1", callcenter_only=False)
        find.assert_called_once_with(
            owner="u1",
            owner_group="g1",
            callcenter_only=False,
            skip=0,
            limit=100,
        )


def test_mark_read_delegates():
    with patch("app.services.NotificationService.notificationRepository.mark_read", return_value=True) as mark:
        assert notification_service.mark_read("id-1", "u1") is True
        mark.assert_called_once_with("id-1", "u1")
