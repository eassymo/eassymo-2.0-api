"""Group search for the share sheet marks shops that already received the request."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import GroupService as svc


def _request():
    return SimpleNamespace(state=SimpleNamespace(_state={"user": {"uid": "u1"}, "groupSelected": "me"}))


def _cursor(docs):
    cursor = MagicMock()
    cursor.sort.return_value.limit.return_value = docs
    cursor.__iter__.return_value = iter(docs)
    return cursor


def test_received_group_ids_reads_sellers_and_followers():
    ids = svc.received_group_ids([
        {"subscribedSellers": ["a", "b"], "subscribedFollowers": ["c"]},
        {"subscribedSellers": ["b"], "subscribedFollowers": None},
        {},
    ])
    assert ids == {"a", "b", "c"}


def test_find_marks_shops_that_already_got_the_parent_request():
    groups = [
        {"_id": "64b000000000000000000001", "name": "Alex", "group_store_type": 2},
        {"_id": "64b000000000000000000002", "name": "Valle", "group_store_type": 2},
    ]
    with patch("app.services.GroupService.groupRepository.find", return_value=_cursor(groups)), \
         patch("app.services.GroupService.partRequestInviteRepository.find", return_value=[]), \
         patch("app.services.GroupService.partRequestRepository.find") as pr_find:
        pr_find.return_value = [{"subscribedSellers": ["64b000000000000000000001"]}]
        result = svc.find(_request(), {"search_argument": "a", "parent_request_id": "parent-1"})

    pr_find.assert_called_once()
    assert pr_find.call_args.args[0] == {"specific_order_uid": "parent-1"}
    by_name = {g.name: g for g in result}
    assert by_name["Alex"].already_received is True
    assert by_name["Valle"].already_received is False
    assert by_name["Valle"].can_be_invited is True


def test_find_without_parent_request_leaves_the_flag_unset():
    groups = [{"_id": "64b000000000000000000001", "name": "Alex", "group_store_type": 2}]
    with patch("app.services.GroupService.groupRepository.find", return_value=_cursor(groups)), \
         patch("app.services.GroupService.partRequestInviteRepository.find", return_value=[]), \
         patch("app.services.GroupService.partRequestRepository.find") as pr_find:
        result = svc.find(_request(), {"search_argument": "a"})

    pr_find.assert_not_called()
    assert result[0].already_received is None


def test_find_for_a_request_leaves_out_the_viewers_own_store():
    groups = [{"_id": "64b000000000000000000002", "name": "Valle", "group_store_type": 2}]
    with patch("app.services.GroupService.groupRepository.find", return_value=_cursor(groups)) as g_find, \
         patch("app.services.GroupService.partRequestInviteRepository.find", return_value=[]), \
         patch("app.services.GroupService.partRequestRepository.find", return_value=[]):
        svc.find(_request(), {"search_argument": "a", "parent_request_id": "parent-1"})

    query = g_find.call_args.args[0]
    assert {"_id": {"$ne": svc._object_id_or_raw("me")}} in query["$and"]


def test_find_without_a_request_keeps_the_viewers_own_store():
    with patch("app.services.GroupService.groupRepository.find", return_value=_cursor([])) as g_find, \
         patch("app.services.GroupService.partRequestInviteRepository.find", return_value=[]):
        svc.find(_request(), {"search_argument": "a"})

    assert "$ne" not in str(g_find.call_args.args[0])
