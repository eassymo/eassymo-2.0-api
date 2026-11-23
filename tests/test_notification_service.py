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


def test_resolve_decisions_delegates_with_now_ms():
    with patch("app.services.NotificationService.notificationRepository.resolve_by_decision_key", return_value=2) as resolve:
        assert notification_service.resolve_decisions("order:o1:confirm") == 2
    key, at_ms = resolve.call_args.args
    assert key == "order:o1:confirm" and isinstance(at_ms, int) and at_ms > 1_700_000_000_000


def test_resolve_decisions_ignores_empty_key():
    assert notification_service.resolve_decisions("") == 0


def test_document_keeps_structured_fields():
    doc = notification_service._to_document({
        "type": "OFFER_CREATED", "message": "m", "ownerGroup": "g", "owner": "u", "metaData": {}, "read": False,
        "title": "T", "body": "B", "side": "buy", "vehicle": "Nissan Versa 2018",
        "action": {"label": "Ver", "href": "/x"}, "decision_key": "k",
    })
    assert (doc["title"], doc["body"], doc["side"], doc["vehicle"], doc["decision_key"]) == ("T", "B", "buy", "Nissan Versa 2018", "k")
    assert doc["action"] == {"label": "Ver", "href": "/x"} and doc["resolved_at"] is None


def test_push_uses_structured_title_and_body():
    from app.services import push_service
    doc = {"owner": "u1", "message": "legacy", "title": "Alex canceló tu pedido", "body": "Rotor: ya se vendió.", "type": "ORDER_CANCELED"}
    with patch.object(push_service, "send_push_to_uid", return_value=1) as send:
        push_service.send_push_from_notification(doc)
    assert send.call_args.kwargs["title"] == "Alex canceló tu pedido"
    assert send.call_args.kwargs["body"] == "Rotor: ya se vendió."


def test_push_legacy_doc_keeps_eassymo_title():
    from app.services import push_service
    with patch.object(push_service, "send_push_to_uid", return_value=1) as send:
        push_service.send_push_from_notification({"owner": "u1", "message": "Pedido listo", "type": "ORDER_SENT"})
    assert send.call_args.kwargs["title"] == "Eassymo" and send.call_args.kwargs["body"] == "Pedido listo"


def test_structured_notification_message_joins_title_and_body():
    from app.factories.NotificationsCreator import structured_notification
    from app.schemas.Notification import NotificationType
    n = structured_notification(type=NotificationType.ORDER_CANCELED, owner="u", owner_group="g", title="Alex canceló tu pedido",
                                body="Rotor: ya se vendió.", side="buy", navigate_to_url="/x", meta_data={})
    assert n.message == "Alex canceló tu pedido. Rotor: ya se vendió." and n.side == "buy"
    bare = structured_notification(type=NotificationType.ORDER_CANCELED, owner="u", owner_group="g", title="Solo título",
                                   body="", side="sell", navigate_to_url="/x", meta_data={})
    assert bare.message == "Solo título" and bare.body is None
