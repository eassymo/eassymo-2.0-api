import json
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import patch

from bson import ObjectId
from starlette.routing import Match

from app.routers.PartRequestInviteRouter import partRequestInviteRouter
from app.services import PartRequestInviteService as svc


def _invite(parent, created_at, name="Taller Hernández", **extra):
    doc = {
        "_id": ObjectId(),
        "parent_request_id": parent,
        "inviter_group": "inviter",
        "inviter_group_name": name,
        "inviter_user": "u1",
        "invited_group": "me",
        "status": "CREATED",
        "created_at": created_at,
    }
    doc.update(extra)
    return doc


def _part_request(parent, **extra):
    doc = {
        "_id": ObjectId(),
        "specific_order_uid": parent,
        "status": "Created",
        "isActive": True,
        "subscribedSellers": ["a", "b", "c", "d"],
        "fulfillment_type": "pickup",
        "vehicleInformation": {"maker": "Nissan", "model": "Altima", "year": "2010",
                               "subModel": "S", "engine": "2.5L"},
        "part": {"tipoParteDescripcion": "Aceite De Dirección Hidráulica", "amount": 1,
                 "unitOfMeasure": "Litro", "position": "Izquierdo"},
    }
    doc.update(extra)
    return doc


def _run(invites, part_requests, offers=(), group=None):
    with patch.object(svc.PartRequestInviteRepository, "find", return_value=iter(invites)) as inv_find, \
         patch.object(svc.PartRequestRepository, "find",
                      side_effect=lambda f, p=None: iter([pr for pr in part_requests
                                                          if pr["specific_order_uid"] in f["specific_order_uid"]["$in"]])), \
         patch.object(svc.OfferRepository, "find", return_value=iter(offers)), \
         patch.object(svc.GroupRepository, "find", return_value=iter(group or [])) as grp:
        result = svc.find_pending_for_group("me")
    return result, inv_find, grp


def test_pending_lists_created_invites_for_the_group_newest_first():
    old = _invite("p1", datetime(2026, 1, 1, tzinfo=timezone.utc))
    new = _invite("p2", datetime(2026, 2, 1, tzinfo=timezone.utc))
    result, inv_find, _ = _run([old, new], [_part_request("p1"), _part_request("p2")])
    inv_find.assert_called_once_with({"invited_group": "me", "status": "CREATED"})
    assert [r["parent_request_id"] for r in result] == ["p2", "p1"]


def test_pending_shapes_vehicle_parts_and_counts():
    pr = _part_request("p1")
    rid = str(pr["_id"])
    offers = [{"group_id": "g1", "request_id": rid}, {"group_id": "g1", "request_id": rid}, {"group_id": "g2", "request_id": rid}]
    result, _, _ = _run([_invite("p1", datetime(2026, 1, 1, tzinfo=timezone.utc))], [pr], offers)
    item = result[0]
    assert item["invited_shops"] == 4
    assert item["quoted_shops"] == 2
    assert item["parts"][0]["unit"] == "Litro"
    assert item["parts"][0]["part_request_id"] == str(pr["_id"])
    assert item["vehicle"]["sub_model"] == "S"
    assert item["fulfillment_type"] == "pickup"
    assert isinstance(item["id"], str) and isinstance(item["created_at"], str)


def test_pending_skips_closed_inactive_or_already_joined():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    invites = [_invite(p, now) for p in ("closed", "inactive", "joined", "ok")]
    prs = [
        _part_request("closed", status="Closed"),
        _part_request("inactive", isActive=False),
        _part_request("joined", subscribedSellers=["me", "x"]),
        _part_request("ok"),
    ]
    result, _, _ = _run(invites, prs)
    assert [r["parent_request_id"] for r in result] == ["ok"]


def test_pending_fills_missing_inviter_name_from_group():
    inv = _invite("p1", datetime(2026, 1, 1, tzinfo=timezone.utc), name=None)
    gid = ObjectId()
    inv["inviter_group"] = str(gid)
    result, _, grp = _run([inv], [_part_request("p1")], group=[{"_id": gid, "name": "Refaccionaria X"}])
    grp.assert_called_once_with({"_id": {"$in": [gid]}}, {"name": 1})
    assert result[0]["inviter_group_name"] == "Refaccionaria X"


def test_pending_batches_lookups_for_many_invites():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    gids = [ObjectId() for _ in range(3)]
    invites = [_invite(p, now, name=None, inviter_group=str(g)) for p, g in zip(("p1", "p2", "p3"), gids)]
    prs = [_part_request(p) for p in ("p1", "p2", "p3")]
    offers = [{"group_id": "g1", "request_id": str(prs[0]["_id"])}, {"group_id": "g2", "request_id": str(prs[0]["_id"])},
              {"group_id": "g1", "request_id": str(prs[2]["_id"])}]
    groups = [{"_id": g, "name": f"Taller {i}"} for i, g in enumerate(gids)]
    with patch.object(svc.PartRequestInviteRepository, "find", return_value=iter(invites)), \
         patch.object(svc.PartRequestRepository, "find", return_value=iter(prs)) as pr_find, \
         patch.object(svc.OfferRepository, "find", return_value=iter(offers)) as off_find, \
         patch.object(svc.GroupRepository, "find", return_value=iter(groups)) as grp_find, \
         patch.object(svc.GroupRepository, "find_by_id") as by_id:
        result = svc.find_pending_for_group("me")
    pr_find.assert_called_once()
    off_find.assert_called_once()
    grp_find.assert_called_once()
    by_id.assert_not_called()
    assert sorted(r["parent_request_id"] for r in result) == ["p1", "p2", "p3"]
    by_parent = {r["parent_request_id"]: r for r in result}
    assert by_parent["p1"]["quoted_shops"] == 2
    assert by_parent["p2"]["quoted_shops"] == 0
    assert by_parent["p3"]["quoted_shops"] == 1
    assert sorted(r["inviter_group_name"] for r in result) == ["Taller 0", "Taller 1", "Taller 2"]


def test_pending_route_is_not_captured_by_find_by_id():
    # httpx (TestClient) is not installed in this env: resolve the route the way
    # Starlette does (first full match wins) and call the endpoint directly.
    scope = {"type": "http", "method": "GET", "path": "/partRequestInvite/pending"}
    matched = next(r for r in partRequestInviteRouter.routes if r.matches(scope)[0] == Match.FULL)
    assert matched.endpoint.__name__ != "find_by_id"

    request = SimpleNamespace(state=SimpleNamespace(_state={"groupSelected": "me"}))
    with patch.object(svc, "find_pending_for_group", return_value=[{"id": "x"}]) as pending, \
         patch.object(svc, "find_by_id") as by_id:
        res = matched.endpoint(request)
    assert res.status_code == 200
    assert json.loads(res.body)["body"] == [{"id": "x"}]
    pending.assert_called_once_with("me")
    by_id.assert_not_called()


def test_pending_returns_empty_without_selected_group():
    with patch.object(svc.PartRequestInviteRepository, "find") as inv_find:
        assert svc.find_pending_for_group("") == []
        assert svc.find_pending_for_group(None) == []
    inv_find.assert_not_called()


def test_update_status_changes_every_matching_invite():
    docs = [_invite("p1", "2026-01-01"), _invite("p1", "2026-01-02")]
    with patch.object(svc.PartRequestInviteRepository, "find", return_value=iter(docs)), \
         patch.object(svc.PartRequestInviteRepository, "find_one_and_update",
                      side_effect=lambda _id, payload: {**payload, "_id": _id}) as upd:
        result = svc.update_status("inviter", "me", "p1", "REJECTED")
    assert upd.call_count == 2
    assert len(result) == 2


def test_update_status_answers_with_and_without_trailing_slash():
    # A redirect from ".../update-status/" makes browsers drop the Authorization header,
    # the retry gets 401 and the client logs the user out. Both spellings must match directly.
    for path in ("/partRequestInvite/update-status", "/partRequestInvite/update-status/"):
        scope = {"type": "http", "method": "PUT", "path": path}
        matched = [r for r in partRequestInviteRouter.routes if r.matches(scope)[0] == Match.FULL]
        assert matched and matched[0].endpoint.__name__ == "update_status", path
