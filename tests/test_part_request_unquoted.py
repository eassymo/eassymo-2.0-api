"""GET /partRequest/unquoted: every part a seller hasn't answered yet, with the real total."""

import json
from unittest.mock import patch

from bson import ObjectId
from starlette.routing import Match

from app.routers.PartRequestRouter import partRequestRouter
from app.services import PartRequestService as svc

R1, R2, R3 = str(ObjectId()), str(ObjectId()), str(ObjectId())


def _doc(rid):
    return {
        "_id": ObjectId(rid),
        "status": "Created",
        "creatorGroup": "buyer-1",
        "creatorUser": "user-1",
        "vehicleId": "veh-1",
        "subscribedSellers": ["g1"],
        "part": "Balatas",
    }


def _run(quoted_ids, docs, total=None, limit=200):
    with patch.object(svc.partRequestRepository, "find_open_ids", return_value=[ObjectId(R1), ObjectId(R2), ObjectId(R3)]) as open_ids, \
            patch.object(svc.offerRepository, "distinct_request_ids_for_group", return_value=quoted_ids) as quoted, \
            patch.object(svc.partRequestRepository, "find_unquoted", return_value=docs) as find, \
            patch.object(svc.partRequestRepository, "count_unquoted", return_value=len(docs) if total is None else total) as count:
        result = svc.find_unquoted_for_seller("g1", limit=limit)
    return result, quoted, find, count


def test_excludes_requests_with_any_offer_from_the_seller():
    # r2 has a sent offer and r3 a "sin stock" one: both are answered.
    result, quoted, find, _ = _run([R2, R3], [_doc(R1)])
    # Only the open requests the seller can see are checked against offers, so the exclusion list stays bounded.
    quoted.assert_called_once_with("g1", [R1, R2, R3])
    filters, excluded = find.call_args.args[0], find.call_args.args[1]
    assert set(excluded) == {ObjectId(R2), ObjectId(R3)}
    assert [item["_id"] for item in result["items"]] == [R1]
    assert result["total"] == 1


def test_filters_match_grouped_role_2():
    _, _, find, _ = _run([], [])
    filters = find.call_args.args[0]
    assert filters["status"] == "Created"
    clauses = filters["$and"]
    assert {"$or": [{"subscribedSellers": "g1"}, {"subscribedFollowers": "g1"}]} in clauses
    assert {"creatorGroup": {"$ne": "g1"}} in clauses


def test_limit_caps_items_but_total_counts_all():
    result, _, find, count = _run([], [_doc(R1)], total=250, limit=200)
    assert find.call_args.kwargs["limit"] == 200
    assert result["total"] == 250


def test_items_carry_no_offers():
    result, *_ = _run([], [_doc(R1)])
    assert result["items"][0].get("offers") in (None, [])


def test_route_returns_items_and_total():
    from app.routers.PartRequestRouter import find_unquoted

    payload = {"items": [{"_id": R1}], "total": 1}
    with patch.object(svc, "find_unquoted_for_seller", return_value=payload) as find:
        response = find_unquoted(group_id="g1", limit=200)
    assert response.status_code == 200
    assert json.loads(response.body)["body"] == payload
    find.assert_called_once_with("g1", limit=200)


def test_route_is_not_swallowed_by_the_id_route():
    scope = {"type": "http", "method": "GET", "path": "/partRequest/unquoted"}
    matched = [r for r in partRequestRouter.routes if r.matches(scope)[0] == Match.FULL]
    assert matched[0].endpoint.__name__ == "find_unquoted"
