from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.schemas.Lists import ListsSchema
from app.services import ListsService as svc

LIST_ID = str(ObjectId())
USER = "user-1"
GROUP = "group-1"


def _payload(**overrides) -> ListsSchema:
    data = {
        "_id": LIST_ID,
        "group_id": GROUP,
        "user_uid": USER,
        "groups": ["g1"],
        "name": "Proveedores",
        "is_priority": False,
        "is_favorite": False,
    }
    data.update(overrides)
    return ListsSchema(**data)


def _prev(**overrides) -> dict:
    prev = {
        "_id": ObjectId(LIST_ID),
        "group_id": GROUP,
        "user_uid": USER,
        "groups": ["g1"],
        "name": "Proveedores",
        "is_priority": False,
        "is_favorite": False,
    }
    prev.update(overrides)
    return prev


def _run_update(prev: dict, payload: ListsSchema):
    with patch.object(svc.listsRepository, "find", return_value=[prev]), \
            patch.object(svc.listsRepository, "update") as update, \
            patch.object(svc.listsRepository, "unset_priority_except") as unset, \
            patch.object(svc.listsRepository, "find_by_user_and_group",
                         return_value=[{**prev, "is_priority": payload.is_priority}]):
        svc.update({}, LIST_ID, payload)
    return update, unset


def test_promoting_a_list_demotes_the_others_and_drops_favorite():
    update, unset = _run_update(_prev(is_favorite=True), _payload(is_priority=True, is_favorite=True))

    saved = update.call_args.args[1]
    assert saved["is_priority"] is True
    assert saved["is_favorite"] is False
    unset.assert_called_once_with(USER, GROUP, LIST_ID)


def test_priority_list_cannot_be_saved_as_favorite():
    update, unset = _run_update(
        _prev(is_priority=True), _payload(is_priority=True, is_favorite=True))

    assert update.call_args.args[1]["is_favorite"] is False
    unset.assert_not_called()  # already the priority list: no demotion pass


def test_current_priority_cannot_be_unset_directly():
    with patch.object(svc.listsRepository, "find", return_value=[_prev(is_priority=True)]), \
            patch.object(svc.listsRepository, "update") as update:
        with pytest.raises(HTTPException) as exc:
            svc.update({}, LIST_ID, _payload(is_priority=False))

    assert exc.value.status_code == 400
    update.assert_not_called()


def test_comisionistas_cannot_become_priority():
    prev = _prev(name="Comisionistas")
    with patch.object(svc.listsRepository, "find", return_value=[prev]), \
            patch.object(svc.listsRepository, "update") as update:
        with pytest.raises(HTTPException) as exc:
            svc.update({}, LIST_ID, _payload(name="Comisionistas", is_priority=True))

    assert exc.value.status_code == 400
    update.assert_not_called()


def test_regular_update_keeps_favorite():
    update, unset = _run_update(_prev(), _payload(is_favorite=True))

    assert update.call_args.args[1]["is_favorite"] is True
    unset.assert_not_called()
