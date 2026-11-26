"""GET /relaciones/historial/{counterpart}: what the selected store has done with one counterpart (the buyer card's
"Tu historial" row): how many orders, how many open / delivered / canceled, the last one, and the latest check-in."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from app.routers import RelationshipRouter as router_mod
from app.schemas.Relationship import RelationshipDirection
from app.services import RelationshipService as svc
from tests.asgi_client import AsgiClient

SELLER = "6abdc235b58274ef264149ba"
BUYER = "6ad43f619a7ad4093bb69d22"


def _order(status, created_at):
    return {"_id": f"o-{status}-{created_at.day}", "status": status, "created_at": created_at,
            "group": BUYER, "offer": {"group_id": SELLER}}


@pytest.fixture
def orders():
    rows = [
        _order("WAITING_FOR_CONFIRMATION", datetime(2026, 11, 24, 22, 0, tzinfo=timezone.utc)),
        _order("RECIEVED", datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)),
        _order("IN_PERSON_COMPLETED", datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)),
        _order("CANCELED", datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)),
    ]
    seen = {}

    def fake_find(filters, *a, **k):
        seen["filters"] = filters
        return list(rows)

    with patch.object(svc.orderRepository, "find", side_effect=fake_find), \
         patch.object(svc.relationshipRepository, "find_latest_perceptions", return_value=[]) as perceptions:
        yield rows, seen, perceptions


def test_counts_orders_by_state_and_gives_the_last_one(orders):
    result = svc.history_with(SELLER, BUYER, RelationshipDirection.VENDIENDO)
    assert result == {
        "orders": 4,
        "open": 1,
        "completed": 2,
        "canceled": 1,
        "last_order_at": "2026-11-24T22:00:00+00:00",
        "answer_label": None,
    }


def test_selling_looks_at_orders_where_the_store_sold_to_that_buyer(orders):
    _, seen, _ = orders
    svc.history_with(SELLER, BUYER, RelationshipDirection.VENDIENDO)
    flat = repr(seen["filters"])
    assert "offer.group_id" in flat and SELLER in flat and "'group'" in flat and BUYER in flat


def test_buying_swaps_the_roles(orders):
    _, seen, _ = orders
    svc.history_with(BUYER, SELLER, RelationshipDirection.COMPRANDO)
    and_ = seen["filters"]["$and"]
    assert any("group" in f and BUYER in repr(f["group"]) for f in and_)
    assert any("offer.group_id" in f and SELLER in repr(f["offer.group_id"]) for f in and_)


def test_includes_the_latest_check_in_answer(orders):
    _, _, perceptions = orders
    perceptions.return_value = [{"counterpart_group_id": BUYER, "answer": "bien"}]
    assert svc.history_with(SELLER, BUYER, RelationshipDirection.VENDIENDO)["answer_label"] == "Bien"
    perceptions.assert_called_with(SELLER, "vendiendo")


def test_no_orders_is_all_zero():
    with patch.object(svc.orderRepository, "find", return_value=[]), \
         patch.object(svc.relationshipRepository, "find_latest_perceptions", return_value=[]):
        assert svc.history_with(SELLER, BUYER, RelationshipDirection.VENDIENDO) == {
            "orders": 0, "open": 0, "completed": 0, "canceled": 0, "last_order_at": None, "answer_label": None,
        }


@pytest.fixture
def client():
    app = FastAPI()

    @app.middleware("http")
    async def selected_group(request, call_next):
        request.state.groupSelected = request.headers.get("groupselected")
        return await call_next(request)

    app.include_router(router_mod.relationshipRouter)
    return AsgiClient(app)


def test_route_uses_the_selected_store_and_checks_membership(client):
    with patch.object(router_mod, "require_authenticated_uid", return_value="uid-1"), \
         patch.object(router_mod, "assert_group_membership") as member, \
         patch.object(router_mod.RelationshipService, "history_with", return_value={"orders": 1}) as history:
        r = client.get(f"/relaciones/historial/{BUYER}?direction=vendiendo", headers={"groupselected": SELLER})
    assert r.status_code == 200 and r.json()["body"] == {"orders": 1}
    member.assert_called_once_with("uid-1", SELLER)
    history.assert_called_once_with(SELLER, BUYER, RelationshipDirection.VENDIENDO)


def test_route_without_a_selected_store_is_400(client):
    with patch.object(router_mod, "require_authenticated_uid", return_value="uid-1"):
        assert client.get(f"/relaciones/historial/{BUYER}").status_code == 400
