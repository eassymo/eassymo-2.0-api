"""Closing a request instead of choosing settles the 'choose another offer' decision (review focus 5). Only the buyer's
store closes it: the caller acts for the request's creator group (the grant is checked there) and belongs to it."""
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException

from app.authz import grant_keys as g
from app.routers import PartRequestRouter as router_mod
from app.services import NotificationService, PartRequestService as svc
from app.services import authz
from tests.asgi_client import AsgiClient
from tests.test_part_removal import store_members

BUYER = str(ObjectId())
OTHER_STORE = str(ObjectId())
DOC = {"_id": "req-1", "creatorGroup": BUYER, "isActive": True, "last_cancellation": {"order_id": "o1"}}
# Members of the buyer's store who are not in its `users` list, and a member of another store.
MEMBERS = dict(
    groups={BUYER: {"users": ["buyer-uid"], "owner": "owner-1"}, OTHER_STORE: {"users": ["seller-1"]}},
    users={"listed-1": {"groups": [BUYER]}},
    roles=[("role-1", BUYER), ("seller-role-1", OTHER_STORE)],
)


def _run(uid="buyer-uid", group_id=BUYER, doc=DOC):
    with patch.object(svc.partRequestRepository, "find_one_by_id", return_value=dict(doc) if doc else None), \
         patch.object(svc.partRequestRepository, "edit_part_request") as edit, \
         store_members(**MEMBERS), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        result = None
        try:
            result = svc.close_part_request("req-1", uid, group_id)
        finally:
            _run.edit, _run.resolve = edit, resolve
    return result


def _error(**kw):
    with pytest.raises(HTTPException) as exc:
        _run(**kw)
    _run.edit.assert_not_called()
    return exc.value.status_code, exc.value.detail


def test_close_resolves_decision_and_unsets_last_cancellation():
    assert _run() == {"_id": "req-1", "isActive": False}
    data = _run.edit.call_args.args[1]
    assert _run.edit.call_args.args[0] == "req-1"
    assert data["isActive"] is False and data["last_cancellation"] is None
    _run.resolve.assert_called_once_with("request:req-1:choose")


@pytest.mark.parametrize("uid", ["owner-1", "listed-1", "role-1"])
def test_any_member_the_grant_check_accepts_may_close(uid):
    """Owner, the user's own groups list, an active role: the same membership require_grant uses."""
    _run(uid=uid)
    assert _run.edit.call_args.args[1]["isActive"] is False


@pytest.mark.parametrize("uid, group_id", [
    ("seller-1", BUYER),  # not a member of the buyer's store
    ("seller-role-1", BUYER),
    ("seller-1", OTHER_STORE),  # acting for another store
    ("buyer-uid", OTHER_STORE),  # a buyer member acting for a store that isn't the request's
])
def test_only_the_buyer_store_can_close(uid, group_id):
    assert _error(uid=uid, group_id=group_id) == (403, "Solo quien creó la solicitud puede cerrarla.")


def test_missing_request_is_404():
    assert _error(doc=None)[0] == 404


# ── Route ────────────────────────────────────────────────────────────────────

@pytest.fixture
def route():
    grants = {"keys": frozenset({g.REQUESTS_EDIT})}
    app = FastAPI()
    app.include_router(router_mod.partRequestRouter)
    with patch.object(authz, "caller_uid", return_value="buyer-uid"), \
         patch.object(authz, "effective_grants", side_effect=lambda *a: grants["keys"]), \
         patch.object(svc, "close_part_request", return_value={"_id": "req-1", "isActive": False}) as close:
        client = AsgiClient(app)
        yield (lambda: client.post("/partRequest/req-1/close", headers={"GroupSelected": BUYER})), close, grants


def test_route_passes_the_caller_and_the_selected_store(route):
    post, close, _ = route

    r = post()

    assert r.status_code == 200, r.text
    close.assert_called_once_with("req-1", "buyer-uid", BUYER)


def test_route_without_the_edit_grant_is_403(route):
    post, close, grants = route
    grants["keys"] = frozenset({g.REQUESTS_VIEW})

    r = post()

    assert r.status_code == 403 and g.REQUESTS_EDIT in r.text
    close.assert_not_called()
