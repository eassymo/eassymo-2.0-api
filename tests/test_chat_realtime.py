import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

# ChatService imports Mongo at module load; stub before import in tests.
sys.modules.setdefault("app.config.database", MagicMock())

from app.services import ChatService as chat_service


def test_group_can_access_part_request_creator():
    doc = {"creatorGroup": "g1", "subscribedSellers": [], "subscribedFollowers": []}
    assert chat_service._group_can_access_part_request_doc(doc, "g1") is True
    assert chat_service._group_can_access_part_request_doc(doc, "g2") is False


def test_group_can_access_part_request_seller_and_follower():
    doc = {
        "creatorGroup": "g1",
        "subscribedSellers": ["g2"],
        "subscribedFollowers": ["g3"],
    }
    assert chat_service._group_can_access_part_request_doc(doc, "g2") is True
    assert chat_service._group_can_access_part_request_doc(doc, "g3") is True


@patch("app.services.ChatService._participant_uids_for_entity", return_value=["uid-1", "uid-2"])
@patch("app.services.ChatService.realtime_bus.grant_chat_acl", return_value=True)
@patch("app.services.ChatService.partRequestRepository.find_one_by_id")
def test_grant_realtime_access_request(mock_find, mock_grant, mock_participants):
    mock_find.return_value = {
        "creatorGroup": "buyer-1",
        "subscribedSellers": ["seller-1"],
        "subscribedFollowers": [],
    }

    granted = chat_service.grant_realtime_access("req-1", "request", "uid-1", "seller-1")

    assert granted is True
    mock_grant.assert_called_once_with("request", "req-1", ["uid-1", "uid-2"])


@patch("app.services.ChatService.partRequestRepository.find_one_by_id", return_value=None)
def test_grant_realtime_access_request_not_found(mock_find):
    with pytest.raises(HTTPException) as exc:
        chat_service.grant_realtime_access("req-missing", "request", "uid-1", "g1")
    assert exc.value.status_code == 404


@patch("app.services.ChatService.partRequestRepository.find_one_by_id")
def test_grant_realtime_access_forbidden(mock_find):
    mock_find.return_value = {
        "creatorGroup": "buyer-1",
        "subscribedSellers": [],
        "subscribedFollowers": [],
    }
    with pytest.raises(HTTPException) as exc:
        chat_service.grant_realtime_access("req-1", "request", "uid-1", "outsider")
    assert exc.value.status_code == 403


@patch("app.services.ChatService._participant_uids_for_entity", return_value=["uid-sender", "uid-seller"])
@patch("app.services.ChatService.realtime_bus.publish_chat_event", return_value="evt-1")
@patch("app.services.ChatService.realtime_bus.grant_chat_acl", return_value=True)
@patch("app.services.ChatService.chatRepository.update_chat")
@patch("app.services.ChatService.chatRepository.find_by_id")
def test_add_message_publishes_event(mock_find, mock_update, mock_grant, mock_publish, mock_participants):
    from app.schemas.Message import Message, MessageType, MessageMetaData
    from datetime import datetime
    from zoneinfo import ZoneInfo

    mock_find.return_value = {
        "_id": "507f1f77bcf86cd799439011",
        "requestId": "req-1",
        "groupId": "buyer-1",
        "createdAt": datetime.now(ZoneInfo("UTC")),
        "updatedAt": datetime.now(ZoneInfo("UTC")),
        "messages": [],
    }

    message = Message(
        chatId="507f1f77bcf86cd799439011",
        type=MessageType.TEXT,
        groupId="seller-1",
        senderId="uid-sender",
        content="hello",
        metaData=MessageMetaData(groupName="G", senderName="S"),
    )

    result = chat_service.add_message(message, "uid-sender", "seller-1")

    assert result is True
    mock_update.assert_called_once()
    mock_grant.assert_called_once_with("request", "req-1", ["uid-sender", "uid-seller"])
    mock_publish.assert_called_once()
    publish_args = mock_publish.call_args[0]
    assert publish_args[0] == "request"
    assert publish_args[1] == "req-1"
