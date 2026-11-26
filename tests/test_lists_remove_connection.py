"""DELETE /lists/connections/{other_group_id}: drop a store from every one of the caller's lists."""
import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("app.config.database", MagicMock())

import pytest
from bson import ObjectId
from fastapi import FastAPI

from app.authz import grant_keys as g
from app.routers import ListsRouter as router_mod
from app.services import ListsService as lists_service
from app.services import authz
from tests.asgi_client import AsgiClient

GROUP_ID = "64b0000000000000000000a1"
OTHER_GROUP_ID = "64b0000000000000000000b1"
MI_RED_ID = "64b000000000000000000001"
FRENOS_ID = "64b000000000000000000002"
COMISIONISTAS_ID = "64b000000000000000000003"
COMISIONABLES_ID = "64b000000000000000000004"
FOREIGN_ID = "64b000000000000000000009"


def _list(list_id, name, user_uid="u1", groups=(OTHER_GROUP_ID,)):
    return {"_id": list_id, "group_id": GROUP_ID, "user_uid": user_uid, "groups": list(groups), "name": name}


@pytest.fixture
def env():
    app = FastAPI()
    app.include_router(router_mod.listRouter)
    state = {
        "grants": {g.NETWORK_MANAGE_LISTS},
        "docs": [_list(MI_RED_ID, "Mi Red"), _list(FRENOS_ID, "frenos")],
    }
    with patch.object(authz, "caller_uid", return_value="u1"), \
         patch.object(authz, "selected_group", return_value=GROUP_ID), \
         patch.object(authz, "effective_grants", side_effect=lambda *a, **k: frozenset(state["grants"])), \
         patch.object(lists_service.listsRepository, "find", side_effect=lambda *a, **k: list(state["docs"])) as find, \
         patch.object(lists_service.listsRepository, "remove_group_from_list") as remove, \
         patch.object(lists_service.listsRepository, "insert_network_event") as event:
        state["find"] = find
        yield AsgiClient(app), remove, event, state


def _delete(client):
    return client.request("DELETE", f"/lists/connections/{OTHER_GROUP_ID}")


def test_removes_from_every_own_list(env):
    client, remove, event, state = env
    r = _delete(client)
    assert r.status_code == 200
    state["find"].assert_called_once_with({
        "user_uid": "u1",
        "group_id": GROUP_ID,
        "groups": {"$in": [OTHER_GROUP_ID, ObjectId(OTHER_GROUP_ID)]},
    })
    assert sorted(r.json()["body"]["removed_from"]) == sorted([MI_RED_ID, FRENOS_ID])
    assert sorted(c.args[0] for c in remove.call_args_list) == sorted([MI_RED_ID, FRENOS_ID])
    assert all(c.args[1] == OTHER_GROUP_ID for c in remove.call_args_list)
    event.assert_called_once()
    doc = event.call_args.args[0]
    assert doc["type"] == "connection_removed"
    assert doc["user_uid"] == "u1" and doc["group_id"] == GROUP_ID and doc["other_group_id"] == OTHER_GROUP_ID
    assert sorted(doc["list_ids"]) == sorted([MI_RED_ID, FRENOS_ID])
    assert doc["at"] is not None


def test_not_connected_is_404(env):
    client, remove, event, state = env
    state["docs"] = []
    r = _delete(client)
    assert r.status_code == 404
    assert r.json()["detail"] == "Esta tienda no está en tu red."
    remove.assert_not_called()
    event.assert_not_called()


def test_commissioner_is_400(env):
    client, remove, event, state = env
    state["docs"] = [_list(MI_RED_ID, "Mi Red"), _list(COMISIONISTAS_ID, "Comisionistas")]
    r = _delete(client)
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "Para quitar un comisionista usa «Quitar» en Mis listas; "
        "así se corta la relación y también se actualiza el comisionado."
    )
    remove.assert_not_called()
    event.assert_not_called()


def test_commissionable_is_400(env):
    client, remove, event, state = env
    state["docs"] = [_list(MI_RED_ID, "Mi Red"), _list(COMISIONABLES_ID, " Comisionables ")]
    r = _delete(client)
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "Esta tienda es parte de tus comisionables; se quita cuando termina la relación con el comisionista."
    )
    remove.assert_not_called()
    event.assert_not_called()


def test_other_users_lists_untouched(env):
    client, remove, _, state = env
    state["docs"] = [_list(MI_RED_ID, "Mi Red"), _list(FOREIGN_ID, "Mi Red", user_uid="u2")]
    r = _delete(client)
    assert r.status_code == 200
    assert r.json()["body"]["removed_from"] == [MI_RED_ID]
    assert FOREIGN_ID not in [c.args[0] for c in remove.call_args_list]


def test_without_grant_is_403(env):
    client, remove, event, state = env
    state["grants"] = set()
    r = _delete(client)
    assert r.status_code == 403
    remove.assert_not_called()
    event.assert_not_called()
