import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

sys.modules.setdefault("app.config.database", MagicMock())

from app.schemas.Lists import ListsSchema
from app.services import ListsService as lists_service

LIST_ID = "64b000000000000000000002"
STORE_A = "64b0000000000000000000a1"
STORE_B = "64b0000000000000000000b2"


def _stored(**overrides):
    doc = {"_id": LIST_ID, "group_id": "g1", "user_uid": "u1", "groups": [STORE_A], "name": " Comisionables ",
           "is_priority": False, "is_favorite": False}
    doc.update(overrides)
    return doc


def _payload(**overrides):
    data = {"_id": LIST_ID, "group_id": "g1", "user_uid": "u1", "groups": [STORE_A], "name": "Comisionables",
            "is_priority": False, "is_favorite": False}
    data.update(overrides)
    return ListsSchema(**data)


def _update(payload):
    stored = _stored()
    with patch.object(lists_service.listsRepository, "find", return_value=[stored]), \
         patch.object(lists_service.listsRepository, "find_by_user_and_group", return_value=[stored]), \
         patch.object(lists_service.listsRepository, "update") as update, \
         patch.object(lists_service.listsRepository, "unset_priority_except"):
        try:
            lists_service.update({}, LIST_ID, payload)
        except HTTPException as error:
            return error, update
    return None, update


def test_removing_a_store_from_comisionables_is_400():
    error, update = _update(_payload(groups=[]))
    assert error is not None and error.status_code == 400
    assert error.detail == (
        "Esta tienda es parte de tus comisionables; se quita cuando termina la relación con el comisionista."
    )
    update.assert_not_called()


def test_adding_a_store_to_comisionables_still_saves():
    # The request creator's stores step and shop-creator-v3 add stores to Comisionables through PUT /lists/{id}.
    error, update = _update(_payload(groups=[STORE_A, STORE_B]))
    assert error is None
    update.assert_called_once()


def test_renaming_comisionables_to_comisionistas_is_400():
    error, update = _update(_payload(name="Comisionistas"))
    assert error is not None and error.status_code == 400
    assert error.detail == "El nombre «Comisionistas» está reservado para la relación con comisionados."
    update.assert_not_called()


def test_saving_comisionables_with_the_same_stores_still_works():
    error, update = _update(_payload())
    assert error is None
    update.assert_called_once()

