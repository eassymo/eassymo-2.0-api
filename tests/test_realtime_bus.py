from unittest.mock import MagicMock, patch

from app.services import realtime_bus


def test_publish_inbox_event_writes_expected_path():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        child = MagicMock()
        get_ref.return_value = child

        event_id = realtime_bus.publish_inbox_event(
            "user-1",
            {"notificationId": "n-1", "type": "OFFER_CREATED"},
        )

        assert event_id is not None
        get_ref.assert_called_once_with(f"events/inbox/user-1/{event_id}")
        child.set.assert_called_once()
        payload = child.set.call_args[0][0]
        assert payload["eventType"] == "notification.created"
        assert payload["notificationId"] == "n-1"
        assert payload["at"] == {"sv": "timestamp"}


def test_publish_inbox_event_skips_empty_uid():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        assert realtime_bus.publish_inbox_event("", {"type": "X"}) is None
        assert realtime_bus.publish_inbox_event("   ", {"type": "X"}) is None
        get_ref.assert_not_called()


def test_publish_inbox_event_rejects_path_injection():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        assert realtime_bus.publish_inbox_event("user/1", {"type": "X"}) is None
        get_ref.assert_not_called()


def test_publish_chat_event_writes_expected_path():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        child = MagicMock()
        get_ref.return_value = child

        event_id = realtime_bus.publish_chat_event(
            "request",
            "req-99",
            {"chatId": "c-1", "messageId": "m-1"},
        )

        assert event_id is not None
        get_ref.assert_called_once_with(f"events/chat/request/req-99/{event_id}")
        child.set.assert_called_once()
        payload = child.set.call_args[0][0]
        assert payload["eventType"] == "message.created"
        assert payload["chatId"] == "c-1"


def test_publish_chat_event_rejects_invalid_type():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        assert realtime_bus.publish_chat_event("invalid", "id", {}) is None  # type: ignore[arg-type]
        get_ref.assert_not_called()


def test_publish_chat_event_rejects_path_injection():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        assert realtime_bus.publish_chat_event("request", "req/id", {}) is None
        get_ref.assert_not_called()


def test_grant_chat_acl_multi_path_update():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        root = MagicMock()
        get_ref.return_value = root

        assert realtime_bus.grant_chat_acl("order", "ord-1", ["u1", "u2", "u1"]) is True

        get_ref.assert_called_once_with("/")
        root.update.assert_called_once_with(
            {
                "acl/chats/order/ord-1/u1": True,
                "acl/chats/order/ord-1/u2": True,
            }
        )


def test_grant_chat_acl_skips_empty_uids():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        assert realtime_bus.grant_chat_acl("request", "r-1", ["", "  "]) is False
        get_ref.assert_not_called()


def test_grant_chat_acl_rejects_invalid_entity_id():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        assert realtime_bus.grant_chat_acl("request", "r/1", ["u1"]) is False
        get_ref.assert_not_called()


def test_publish_returns_none_on_rtdb_error():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        child = MagicMock()
        child.set.side_effect = RuntimeError("rtdb down")
        get_ref.return_value = child

        assert realtime_bus.publish_inbox_event("user-1", {"type": "X"}) is None


def test_grant_chat_acl_returns_false_on_rtdb_error():
    with patch("app.services.realtime_bus.get_database_reference") as get_ref:
        root = MagicMock()
        root.update.side_effect = RuntimeError("rtdb down")
        get_ref.return_value = root

        assert realtime_bus.grant_chat_acl("request", "r-1", ["u1"]) is False
