"""Cotizador day chips: the days with open requests for a seller, and how many of each day's turns still need quoting."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId
from fastapi import FastAPI

from app.repositories import PartRequestRepository as repo
from app.repositories import RequestStatusByGroupRepository as rsbg_repo
from app.routers.PartRequestRouter import partRequestRouter
from app.services import PartRequestService as svc
from tests.asgi_client import AsgiClient

NOW = datetime(2026, 11, 25, 18, 0, tzinfo=timezone.utc)  # 12:00 in Mexico City
SINCE = datetime(2026, 9, 27, 6, 0, tzinfo=timezone.utc)  # local midnight, 59 days before 25 nov

P1, P2, P3 = ObjectId(), ObjectId(), ObjectId()


SAFE_DATE = {"$convert": {"input": "$createdAt", "to": "date", "onError": None, "onNull": None}}


def _pipeline(tz="America/Mexico_City"):
    col = MagicMock()
    col.aggregate.return_value = []
    with patch.object(repo.database, "db", {"PartRequests": col}):
        list(repo.open_turn_days("seller-1", SINCE, tz))
    return col.aggregate.call_args[0][0]


def test_repository_pipeline_scope_window_and_local_day():
    pipeline = _pipeline()
    assert pipeline[0]["$match"] == {
        "subscribedSellers": "seller-1",
        "status": "Created",
        "$expr": {"$gte": [SAFE_DATE, SINCE]},
    }
    day = pipeline[1]["$project"]["day"]
    assert day == {"$dateToString": {"format": "%Y-%m-%d", "date": SAFE_DATE, "timezone": "America/Mexico_City"}}
    group = pipeline[2]["$group"]
    assert group["_id"] == {"day": "$day", "batch": repo._BATCH_KEY}
    assert group["part_ids"] == {"$push": "$_id"}


def test_text_created_at_lands_on_its_local_day():
    # 25 docs store createdAt as ISO text: both the window and the day convert it to a date, so none are dropped.
    # A text that is not a date becomes null (left out) instead of failing the whole aggregation.
    pipeline = _pipeline()
    assert pipeline[0]["$match"]["$expr"]["$gte"][0] == SAFE_DATE
    assert pipeline[1]["$project"]["day"]["$dateToString"]["date"] == SAFE_DATE


def test_local_day_uses_the_time_zone():
    # 21:30 in Mexico City is 03:30 UTC the next day: the day is cut in the seller's zone, not UTC.
    pipeline = _pipeline("America/Tijuana")
    assert pipeline[1]["$project"]["day"]["$dateToString"]["timezone"] == "America/Tijuana"


def test_repository_flattens_rows():
    col = MagicMock()
    col.aggregate.return_value = [{"_id": {"day": "2026-11-25", "batch": "b1"}, "part_ids": [P1]}]
    with patch.object(repo.database, "db", {"PartRequests": col}):
        rows = list(repo.open_turn_days("seller-1", SINCE, "America/Mexico_City"))
    assert rows == [{"day": "2026-11-25", "batch": "b1", "part_ids": [P1]}]


def test_status_by_group_distinct_request_ids_matches_text_and_object_ids():
    col = MagicMock()
    col.distinct.return_value = [str(P1)]
    with patch.object(rsbg_repo, "db", col):
        out = rsbg_repo.distinct_request_ids_for_group("seller-1", [P1, P2])
    assert out == [str(P1)]
    field, filters = col.distinct.call_args[0]
    assert field == "request_id"
    assert filters["group_id"] == "seller-1"
    assert set(filters["request_id"]["$in"]) == {str(P1), str(P2), P1, P2}


def test_status_by_group_distinct_request_ids_skips_empty():
    col = MagicMock()
    with patch.object(rsbg_repo, "db", col):
        assert rsbg_repo.distinct_request_ids_for_group("seller-1", []) == []
    col.distinct.assert_not_called()


def _days(rows, offered=(), discarded=(), tz="America/Mexico_City"):
    with patch.object(svc.partRequestRepository, "open_turn_days", return_value=rows) as find, \
            patch.object(svc.offerRepository, "distinct_request_ids_for_group", return_value=list(offered)), \
            patch.object(svc.requestStatusByGroupRepository, "distinct_request_ids_for_group", return_value=list(discarded)):
        out = svc.find_open_turn_days("seller-1", tz, NOW)
    return out, find


def test_batch_spanning_days_counts_once_per_day():
    rows = [
        {"day": "2026-11-25", "batch": "b1", "part_ids": [P3]},
        {"day": "2026-11-19", "batch": "b1", "part_ids": [P2]},
        {"day": "2026-11-10", "batch": "b1", "part_ids": [P1]},
    ]
    out, find = _days(rows, offered=[P1])
    assert out == [
        {"day": "2026-11-25", "turns": 1, "to_quote": 1},
        {"day": "2026-11-19", "turns": 1, "to_quote": 1},
        {"day": "2026-11-10", "turns": 1, "to_quote": 0},
    ]
    assert find.call_args[0] == ("seller-1", SINCE, "America/Mexico_City")


def test_day_counts_batches_and_unanswered_batches():
    rows = [
        {"day": "2026-11-24", "batch": "b1", "part_ids": [P1, P2]},  # one part answered, one not → to quote
        {"day": "2026-11-25", "batch": "b2", "part_ids": [P3]},
        {"day": "2026-11-24", "batch": "b3", "part_ids": [P3]},  # answered (offer on P3)
    ]
    out, _ = _days(rows, offered=[str(P1), str(P3)])
    assert out == [
        {"day": "2026-11-25", "turns": 1, "to_quote": 0},
        {"day": "2026-11-24", "turns": 2, "to_quote": 1},
    ]


def test_discarded_part_counts_as_answered():
    rows = [{"day": "2026-11-25", "batch": "b1", "part_ids": [P1]}]
    out, _ = _days(rows, discarded=[str(P1)])
    assert out == [{"day": "2026-11-25", "turns": 1, "to_quote": 0}]


def test_answered_ids_ask_offers_with_text_ids():
    # Offers store request_id as text: asking with ObjectIds matched nothing, so offers never counted as answered.
    with patch.object(svc.offerRepository, "distinct_request_ids_for_group", return_value=[str(P1)]) as offers, \
            patch.object(svc.requestStatusByGroupRepository, "distinct_request_ids_for_group", return_value=[]):
        answered = svc.answered_request_ids("seller-1", [P1, P2])
    assert offers.call_args[0] == ("seller-1", [str(P1), str(P2)])
    assert answered == {str(P1)}


def test_unknown_tz_falls_back_to_mexico_city():
    for tz in (None, "", "Mars/Olympus"):
        _, find = _days([], tz=tz)
        assert find.call_args[0] == ("seller-1", SINCE, "America/Mexico_City")


def test_route_returns_days():
    app = FastAPI()
    app.include_router(partRequestRouter)
    client = AsgiClient(app)
    days = [{"day": "2026-11-25", "turns": 5, "to_quote": 4}]
    with patch.object(svc, "find_open_turn_days", return_value=days) as find:
        resp = client.get("/partRequest/turn-days?seller_group_id=seller-1&tz=America/Mexico_City")
    assert resp.status_code == 200, resp.text
    assert json.loads(resp.text)["body"] == days
    assert find.call_args[0][:2] == ("seller-1", "America/Mexico_City")


def test_route_requires_seller_group_id():
    app = FastAPI()
    app.include_router(partRequestRouter)
    client = AsgiClient(app)
    with patch.object(svc, "find_open_turn_days") as find:
        resp = client.get("/partRequest/turn-days")
    assert resp.status_code == 400
    find.assert_not_called()
