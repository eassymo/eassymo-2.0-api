"""Cotizador turns: every open request for a seller on one day, any buyer, in arrival order."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId
from fastapi import FastAPI

from app.repositories import PartRequestRepository as repo
from app.routers.PartRequestRouter import partRequestRouter
from app.services import PartRequestService as svc
from tests.asgi_client import AsgiClient

FROM = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)
TO = datetime(2026, 11, 26, 6, 0, tzinfo=timezone.utc)


def _pr(rid, buyer, created, vehicle=True):
    return {
        "_id": ObjectId(rid),
        "status": "Created",
        "creatorGroup": buyer,
        "creatorUser": "u1",
        "vehicleId": "veh-1",
        "subscribedSellers": ["seller-1"],
        "part": {"tipoParteDescripcion": "Balatas"},
        "createdAt": created,
        "vehicleInformation": {"maker": "Nissan", "model": "Versa", "year": "2018", "subModel": "Sense", "group": buyer, "user": "u1"} if vehicle else None,
    }


R1, R2, R3 = str(ObjectId()), str(ObjectId()), str(ObjectId())


def test_repository_matches_seller_day_and_sorts_by_arrival():
    col = MagicMock()
    col.aggregate.return_value = []
    with patch.object(repo.database, "db", {"PartRequests": col}):
        list(repo.find_grouped_by_parent_request_uid(None, "seller-1", None, None, created_from=FROM, created_to=TO))
    pipeline = col.aggregate.call_args[0][0]
    # Some writers stored createdAt as ISO text: the day matches either kind.
    assert pipeline[0]["$match"] == {
        "subscribedSellers": "seller-1",
        "$or": [
            {"createdAt": {"$gte": FROM, "$lt": TO}},
            {"createdAt": {"$gte": "2026-11-25T06:00:00.000Z", "$lt": "2026-11-26T06:00:00.000Z"}},
        ],
    }
    group = pipeline[1]["$group"]
    # A request with no parent uid is its own turn (or groups by its order), never one "" bucket.
    assert group["_id"] == {
        "$cond": [
            {"$gt": [{"$strLenCP": {"$ifNull": ["$parent_request_uid", ""]}}, 0]},
            "$parent_request_uid",
            {"$ifNull": ["$specific_order_uid", {"$toString": "$_id"}]},
        ]
    }
    assert group["first_created"] == {"$min": {"$convert": {"input": "$createdAt", "to": "date", "onError": None, "onNull": None}}}
    assert pipeline[2] == {"$sort": {"first_created": 1, "_id": 1}}


def test_repository_without_window_keeps_old_match():
    col = MagicMock()
    col.aggregate.return_value = []
    with patch.object(repo.database, "db", {"PartRequests": col}):
        list(repo.find_grouped_by_parent_request_uid("buyer-1", "seller-1", None, None))
    assert col.aggregate.call_args[0][0][0]["$match"] == {"creatorGroup": "buyer-1", "subscribedSellers": "seller-1"}


def _service(groups, quoted, groups_by_id, discarded=()):
    with patch.object(svc.partRequestRepository, "find_grouped_by_parent_request_uid", return_value=groups) as find, \
            patch.object(svc.offerRepository, "distinct_request_ids_for_group", return_value=quoted) as distinct, \
            patch.object(svc.requestStatusByGroupRepository, "distinct_request_ids_for_group", return_value=list(discarded)), \
            patch.object(svc.groupRepository, "find_by_id", side_effect=lambda gid: groups_by_id.get(gid)):
        out = svc.find_grouped_by_parent_request_uid(None, "seller-1", "Created", None, created_from=FROM, created_to=TO)
    return out, find, distinct


def test_service_adds_buyer_arrival_and_quoted_count():
    t1 = datetime(2026, 11, 25, 15, 5, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 25, 16, 30, tzinfo=timezone.utc)
    groups = [
        {"_id": "p1", "first_created": t1, "part_requests": [_pr(R1, "buyer-a", t1), _pr(R2, "buyer-a", t1)]},
        {"_id": "p2", "first_created": t2, "part_requests": [_pr(R3, "buyer-b", t2)]},
    ]
    out, find, distinct = _service(groups, [ObjectId(R1)], {"buyer-a": {"name": "Servicio Garza"}, "buyer-b": {"name": "Franco 3"}})

    assert find.call_args.kwargs == {"created_from": FROM, "created_to": TO}
    assert distinct.call_args[0][0] == "seller-1"
    assert [g["creator_group_id"] for g in out] == ["buyer-a", "buyer-b"]
    assert [g["creator_group"] for g in out] == ["Servicio Garza", "Franco 3"]
    assert [g["part_count"] for g in out] == [2, 1]
    assert [g["quoted_count"] for g in out] == [1, 0]
    assert out[0]["created_at"].startswith("2026-11-25T15:05")
    assert out[0]["car_data"] == "Nissan Versa 2018"
    assert "first_created" not in out[0]


def test_service_survives_missing_vehicle_and_buyer():
    t1 = datetime(2026, 11, 25, 15, 5, tzinfo=timezone.utc)
    groups = [{"_id": "p1", "first_created": t1, "part_requests": [_pr(R1, "gone", t1, vehicle=False)]}]
    out, _, _ = _service(groups, [], {})
    assert out[0]["creator_group"] == ""
    assert out[0]["car_data"] == ""
    assert out[0]["quoted_count"] == 0


def test_quoted_count_includes_discards():
    t1 = datetime(2026, 11, 25, 15, 5, tzinfo=timezone.utc)
    parts = [_pr(R1, "buyer-a", t1), _pr(R2, "buyer-a", t1), _pr(R3, "buyer-a", t1)]
    groups = [{"_id": "p1", "first_created": t1, "part_requests": parts}]
    # R1 has an offer, R2 was discarded in the cotizador, R3 is untouched.
    out, _, _ = _service(groups, [ObjectId(R1)], {"buyer-a": {"name": "Servicio Garza"}}, discarded=[R2])
    assert out[0]["quoted_count"] == 2


def test_route_passes_the_day_window():
    app = FastAPI()
    app.include_router(partRequestRouter)
    client = AsgiClient(app)
    with patch.object(svc, "find_grouped_by_parent_request_uid", return_value=[]) as find:
        resp = client.get(
            "/partRequest/group/group-by-parent"
            "?seller_group_id=seller-1&part_request_status=Created"
            "&created_from=2026-11-25T06:00:00Z&created_to=2026-11-26T06:00:00Z"
        )
    assert resp.status_code == 200, resp.text
    assert json.loads(resp.text)["body"] == []
    assert find.call_args.kwargs == {"created_from": FROM, "created_to": TO}


def test_route_rejects_a_bad_window():
    app = FastAPI()
    app.include_router(partRequestRouter)
    client = AsgiClient(app)
    resp = client.get("/partRequest/group/group-by-parent?seller_group_id=s&created_from=ayer")
    assert resp.status_code == 400
