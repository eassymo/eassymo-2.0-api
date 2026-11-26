"""The reach endpoint counts only offers the buyer can see: Created and Selected."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import FastAPI

from app.routers import SellerReachRouter as store_mod
from tests.test_seller_reach_routes import GID, TODAY, _Client, _doc


def _matches(doc, filters):
    return all(doc.get(k) in cond["$in"] for k, cond in filters.items())


def _offer(request_id, group_id, status, price):
    return {"_id": ObjectId(), "request_id": request_id, "group_id": group_id, "status": status, "price": price}


@pytest.fixture
def env():
    a, b = str(ObjectId()), str(ObjectId())
    offers = []

    def find(filters, projection):
        return [{"_id": o["_id"], **{k: o[k] for k in projection}} for o in offers if _matches(o, filters)]

    with patch.object(store_mod.group_auth, "user_belongs_to_group", side_effect=lambda u, g: (u, g) == ("u1", GID)), \
         patch.object(store_mod, "reach") as svc, patch.object(store_mod, "partRequestRepository") as prr, \
         patch.object(store_mod, "offerRepository") as offr:
        svc.today.return_value = TODAY
        svc.audience.return_value = 20
        svc.room.return_value = 0
        prr.find_by_specific_order_uid.return_value = [_doc(a), _doc(b)]
        offr.find.side_effect = find
        app = FastAPI()
        app.include_router(store_mod.sellerReachRouter)
        yield SimpleNamespace(offers=offers, ids=(a, b), user=_Client(app, {"uid": "u1"}))


def _reach(env):
    r = env.user.get("/seller-reach/requests/so1")
    assert r.status_code == 200
    return r.json()["body"]


def test_drafts_and_withdrawn_offers_are_not_answers(env):
    a, _ = env.ids
    env.offers += [_offer(a, "g1", "Pending_Changes", 900), _offer(a, "g2", "No_Inventory", 800)]
    body = _reach(env)
    assert body["responded_total"] == 0
    assert body["offers_total"] == 0
    assert body["lowest_price"] is None


def test_counts_visible_offers_and_lowest_price(env):
    a, _ = env.ids
    env.offers += [
        _offer(a, "g1", "Created", 1250),
        _offer(a, "g1", "Created", 1400),
        _offer(a, "g2", "Selected", 1300),
    ]
    body = _reach(env)
    assert body["responded_total"] == 2
    assert body["offers_total"] == 3
    assert body["lowest_price"] == 1250


def test_other_parts_offers_count_too(env):
    a, b = env.ids
    env.offers += [
        _offer(a, "g1", "Created", 2100),
        _offer(b, "g2", "Created", 1800),
        _offer(b, "g3", "Selected", None),
        _offer(b, "g4", "Pending_Changes", 500),
        _offer(str(ObjectId()), "g5", "Created", 100),  # another order's part
    ]
    body = _reach(env)
    assert body["responded_total"] == 3
    assert body["offers_total"] == 3
    assert body["lowest_price"] == 1800
