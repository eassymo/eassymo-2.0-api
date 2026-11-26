"""DELETE /lists/{list_id}: only the caller's own lists in the selected group; system lists stay."""
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

LIST_ID = "64b000000000000000000001"
GROUP_ID = "64b0000000000000000000a1"
OTHER_GROUP_ID = "64b0000000000000000000a2"


def _doc(**overrides):
    doc = {"_id": LIST_ID, "group_id": GROUP_ID, "user_uid": "u1", "groups": [], "name": "frenos",
           "is_priority": False, "is_favorite": False}
    doc.update(overrides)
    return doc


@pytest.fixture
def env():
    app = FastAPI()
    app.include_router(router_mod.listRouter)
    state = {"grants": {g.NETWORK_MANAGE_LISTS}, "docs": [_doc()]}
    with patch.object(authz, "caller_uid", return_value="u1"), \
         patch.object(authz, "selected_group", return_value=GROUP_ID), \
         patch.object(authz, "effective_grants", side_effect=lambda *a, **k: frozenset(state["grants"])), \
         patch.object(lists_service.listsRepository, "find", side_effect=lambda *a, **k: list(state["docs"])) as find, \
         patch.object(lists_service.listsRepository, "archive_and_delete") as archive:
        state["find"] = find
        yield AsgiClient(app), archive, state


def test_deletes_own_list_and_archives_it(env):
    client, archive, state = env
    r = client.request("DELETE", f"/lists/{LIST_ID}")
    assert r.status_code == 200
    state["find"].assert_called_once_with({"_id": ObjectId(LIST_ID)})
    assert r.json() == {"body": {"deleted": LIST_ID}}
    archive.assert_called_once()
    assert archive.call_args.kwargs["deleted_by"] == "u1"


def test_refuses_mi_red(env):
    client, archive, state = env
    state["docs"] = [_doc(name=" Mi Red ")]
    r = client.request("DELETE", f"/lists/{LIST_ID}")
    assert r.status_code == 400
    assert r.json()["detail"] == "«Mi Red» no se puede eliminar."
    archive.assert_not_called()


def test_refuses_comisionistas(env):
    client, archive, state = env
    state["docs"] = [_doc(name="Comisionistas")]
    r = client.request("DELETE", f"/lists/{LIST_ID}")
    assert r.status_code == 400
    assert r.json()["detail"] == "«Comisionistas» no se puede eliminar."
    archive.assert_not_called()


def test_refuses_comisionables(env):
    client, archive, state = env
    state["docs"] = [_doc(name=" Comisionables ")]
    r = client.request("DELETE", f"/lists/{LIST_ID}")
    assert r.status_code == 400
    assert r.json()["detail"] == "«Comisionables» no se puede eliminar."
    archive.assert_not_called()


def test_other_users_list_is_404(env):
    client, archive, state = env
    state["docs"] = [_doc(user_uid="u2")]
    r = client.request("DELETE", f"/lists/{LIST_ID}")
    assert r.status_code == 404
    archive.assert_not_called()


def test_other_group_is_404(env):
    client, archive, state = env
    state["docs"] = [_doc(group_id=OTHER_GROUP_ID)]
    r = client.request("DELETE", f"/lists/{LIST_ID}")
    assert r.status_code == 404
    archive.assert_not_called()


def test_without_grant_is_403(env):
    client, archive, state = env
    state["grants"] = set()
    r = client.request("DELETE", f"/lists/{LIST_ID}")
    assert r.status_code == 403
    archive.assert_not_called()
