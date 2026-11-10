import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("app.config.database", MagicMock())

from app.schemas.Lists import ListsSchema
from app.services import ListsService as lists_service

LIST_ID = "64b000000000000000000001"


def _payload(**overrides):
    data = {
        "_id": LIST_ID,
        "group_id": "g1",
        "user_uid": "u1",
        "groups": [],
        "name": "Taller",
        "is_priority": True,
        "is_favorite": True,
    }
    data.update(overrides)
    return ListsSchema(**data)


def _stored(**overrides):
    doc = {"_id": LIST_ID, "group_id": "g1", "user_uid": "u1", "groups": [], "name": "Taller",
           "is_priority": False, "is_favorite": False}
    doc.update(overrides)
    return doc


def test_making_a_list_priority_demotes_the_others_and_keeps_favorite():
    stored = _stored()
    updated = _stored(is_priority=True, is_favorite=True)
    with patch.object(lists_service.listsRepository, "find", return_value=[stored]), \
         patch.object(lists_service.listsRepository, "find_by_user_and_group", return_value=[updated]), \
         patch.object(lists_service.listsRepository, "update") as update, \
         patch.object(lists_service.listsRepository, "unset_priority_except") as unset:
        result = lists_service.update({}, LIST_ID, _payload())

    saved = update.call_args[0][1]
    assert saved["is_priority"] is True
    assert saved["is_favorite"] is True  # a prioritaria list can also be favorite
    unset.assert_called_once_with("u1", "g1", LIST_ID)
    assert result["is_priority"] is True


def test_non_priority_update_does_not_touch_other_lists():
    stored = _stored()
    with patch.object(lists_service.listsRepository, "find", return_value=[stored]), \
         patch.object(lists_service.listsRepository, "find_by_user_and_group", return_value=[stored]), \
         patch.object(lists_service.listsRepository, "update"), \
         patch.object(lists_service.listsRepository, "unset_priority_except") as unset:
        lists_service.update({}, LIST_ID, _payload(is_priority=False))

    unset.assert_not_called()


def test_default_connection_goes_to_mi_red_even_when_another_list_is_priority():
    user_lists = [
        {"_id": "a", "name": "Taller", "is_priority": True},
        {"_id": "b", "name": "Mi Red", "is_priority": False},
    ]
    assert lists_service._resolve_priority_list_id(user_lists, _payload()) == "b"


def test_default_connection_falls_back_to_priority_list_without_mi_red():
    user_lists = [{"_id": "a", "name": "Taller", "is_priority": True}]
    assert lists_service._resolve_priority_list_id(user_lists, _payload()) == "a"
