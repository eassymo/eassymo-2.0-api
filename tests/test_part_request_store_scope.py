"""The seller-facing reads of a request (sibling and vehicle lists) show a caller outside the buyer's store only its own
store's offers and entries, the same rule as GET /partRequest/{id}; the buyer's store sees everything."""
import json
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest
from bson import ObjectId
from fastapi import FastAPI

from app.routers import PartRequestRouter as pr_router
from app.services import PartRequestService as service
from tests.asgi_client import AsgiClient
from tests.test_offer_before_change import BUYER, GET_MEMBERS, OTHER_STORE, STORE, _archived, _offer, _part
from tests.test_part_removal import _matches, store_members

CANCEL = {"order_id": "o1", "store_group_id": OTHER_STORE, "store_name": "Otra", "reason": "no_stock", "note": ""}
NON_COMPATIBLE = [{"group_id": STORE, "reason": "armadora"}, {"group_id": OTHER_STORE, "reason": "sistemas"}]


def _parts(**live_extra):
    live = _part(**{"parent_request_uid": "p-1", "specific_order_uid": "so-1",
                    "subscribedFollowers": [STORE, OTHER_STORE], "nonCompatibleSellers": NON_COMPATIBLE,
                    "last_cancellation": CANCEL, "last_change": {"by": "b1", "at": "2026-11-27T10:00:00Z", "fields": []},
                    **live_extra})
    removed = _part(parent_request_uid="p-1", specific_order_uid="so-1", isActive=False,
                    removed={"by": "b1", "at": "2026-11-27T11:00:00Z"})
    rid, removed_id = str(live["_id"]), str(removed["_id"])
    offers = [_offer(rid, STORE, 300), _offer(rid, OTHER_STORE, 280), _offer(rid, STORE, 310)]
    archived = [_archived(removed_id, STORE, 185), _archived(removed_id, OTHER_STORE, 200)]
    return [live, removed], offers, archived


def _read(endpoint, uid="u1", group=BUYER, query="", **live_extra):
    """GET one of the list endpoints as `uid` (None: no signed-in user) acting for `group` (None: no header)."""
    parts, offers, archived = _parts(**live_extra)
    app = FastAPI()

    @app.middleware("http")
    async def signed_in(request, call_next):
        if uid:
            request.state.user = {"uid": uid}
        return await call_next(request)

    app.include_router(pr_router.partRequestRouter)
    collection = MagicMock()
    collection.aggregate.side_effect = lambda pipeline: [{**p, "createdAtDate": service.datetime(2026, 11, 27)}
                                                         for p in parts]
    collection.find.return_value.sort.return_value.limit.return_value = parts
    url = {"sibling": "/partRequest/sibling-requests-with-offers/p-1?x=1",
           "vehicle": f"/partRequest/vehicle-requests-with-offers/v?creator_group_id={BUYER}"}[endpoint] + query
    with patch("app.config.database.db", {"PartRequests": collection}), \
         patch.object(service.offerRepository, "find", side_effect=lambda f: [o for o in offers if _matches(o, f)]), \
         patch.object(service.offerArchiveRepository, "find",
                      side_effect=lambda f: [o for o in archived if _matches(o, f)]), \
         patch.object(service.listService, "get_followers_not_in_my_lists", return_value=[]), \
         patch.object(service.listService, "get_groups_in_user_lists", return_value=[STORE, OTHER_STORE]), \
         patch.object(service.groupRepository, "find_by_id", return_value={"_id": ObjectId(STORE), "name": "g"}), \
         patch.object(service, "GroupSchema", side_effect=lambda **kw: MagicMock(toJson=lambda: {"name": "g"})), \
         patch.object(service, "__check_if_group_is_favorite", return_value=False), \
         patch.object(service, "__check_if_group_is_in_non_favorite_list", return_value=False), \
         store_members(**GET_MEMBERS):
        r = AsgiClient(app).get(url, headers={"GroupSelected": group} if group else None)
    assert r.status_code == 200, r.text
    return r.json()["body"], parts


def _live(body, parts):
    return next(p for p in body if p["_id"] == str(parts[0]["_id"]))


ENDPOINTS = ["sibling", "vehicle"]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("uid", ["u1", "role-1"])
def test_buyer_sees_every_offer_and_entry(endpoint, uid):
    body, parts = _read(endpoint, uid=uid)
    live = _live(body, parts)
    assert sorted(o["group_id"] for o in live["offers"]) == sorted([STORE, STORE, OTHER_STORE])
    assert sorted(live["subscribedSellers"]) == sorted([STORE, OTHER_STORE])
    assert sorted(live["subscribedFollowers"]) == sorted([STORE, OTHER_STORE])
    assert [s["group_id"] for s in live["nonCompatibleSellers"]] == [STORE, OTHER_STORE]
    assert live["last_cancellation"]["store_group_id"] == OTHER_STORE
    assert live["last_change"]["by"] == "b1"
    assert len(body) == 1  # the buyer's lists leave out the part it removed


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("uid", ["s1", "seller-role-1"])
@pytest.mark.parametrize("asked", ["", f"&offer_owner_group={STORE}", f"&offer_owner_group={OTHER_STORE}"])
def test_seller_sees_only_its_own_offers_and_entries_whatever_store_it_asks_for(endpoint, uid, asked):
    body, parts = _read(endpoint, uid=uid, group=STORE, query=asked)
    live = _live(body, parts)
    assert [o["group_id"] for o in live["offers"]] == [STORE, STORE]
    assert live["subscribedSellers"] == [STORE]
    assert live["subscribedFollowers"] == [STORE]
    assert live["nonCompatibleSellers"] == [{"group_id": STORE, "reason": "armadora"}]
    assert live["last_cancellation"] is None
    assert "by" not in live["last_change"]
    removed = next(p for p in body if p["_id"] == str(parts[1]["_id"]))
    assert removed["discarded_offers"] == [{"price": 185.0, "count": 1}]
    assert "by" not in removed["removed"]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_seller_sees_its_own_cancellation(endpoint):
    with patch.dict(CANCEL, {"store_group_id": STORE}):
        body, parts = _read(endpoint, uid="s1", group=STORE)
    assert _live(body, parts)["last_cancellation"]["order_id"] == "o1"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_seller_filters_never_reach_other_stores_offers(endpoint):
    """A buyer-list filter names stores; for a seller it can only narrow down to its own offers."""
    filters = quote(json.dumps([{"type": "followers_custom", "values": [OTHER_STORE]}]))
    body, parts = _read(endpoint, uid="s1", group=STORE, query=f"&offer_owner_group={STORE}&filters={filters}")
    assert _live(body, parts)["offers"] == []

    filters = quote(json.dumps([{"type": "connected", "values": ["true"]}]))
    body, parts = _read(endpoint, uid="s1", group=STORE, query=f"&filters={filters}")
    assert [o["group_id"] for o in _live(body, parts)["offers"]] == [STORE, STORE]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("uid, group", [
    ("s1", OTHER_STORE),  # a store it doesn't belong to
    ("u1", STORE),  # a buyer member claiming a seller store
    ("u1", None),  # no selected store
    (None, None),  # anonymous
    (None, STORE),
])
def test_caller_without_a_store_of_its_own_sees_no_offers_or_entries(endpoint, uid, group):
    body, parts = _read(endpoint, uid=uid, group=group, query=f"&offer_owner_group={OTHER_STORE}")
    assert [p["_id"] for p in body] == [str(parts[0]["_id"])]
    live = body[0]
    assert live["offers"] == []
    assert live["subscribedSellers"] == [] and live["subscribedFollowers"] == []
    assert live["nonCompatibleSellers"] == [] and live["last_cancellation"] is None
    assert "by" not in live["last_change"]


# --- GET /partRequest/{id}: subscribedFollowers too ------------------------------------------------------------------

def test_get_by_id_keeps_only_the_sellers_own_follower_entry():
    from tests.test_offer_before_change import _live_part_with_offers

    seller, _ = _live_part_with_offers(uid="s1", group=STORE, subscribedFollowers=[STORE, OTHER_STORE])
    buyer, _ = _live_part_with_offers(subscribedFollowers=[STORE, OTHER_STORE])
    anonymous, _ = _live_part_with_offers(uid=None, group=None, subscribedFollowers=[STORE, OTHER_STORE])
    assert seller["subscribedFollowers"] == [STORE]
    assert sorted(buyer["subscribedFollowers"]) == sorted([STORE, OTHER_STORE])
    assert anonymous["subscribedFollowers"] == []


def test_get_by_id_keeps_no_followers_stored_as_none():
    """part-request-chat asks the live follower list when the request stored none: keep "none" as None."""
    from tests.test_offer_before_change import _live_part_with_offers

    seller, _ = _live_part_with_offers(uid="s1", group=STORE, subscribedFollowers=None)
    assert seller["subscribedFollowers"] is None


# --- One rule for every per-store list: None stays None, a list keeps only the caller's own entries ------------------

STORE_KEYS = {
    "subscribedSellers": ([STORE, OTHER_STORE], [STORE]),
    "subscribedFollowers": ([STORE, OTHER_STORE], [STORE]),
    "capped_sellers": ([STORE, OTHER_STORE], [STORE]),
    "nonCompatibleSellers": (NON_COMPATIBLE, [{"group_id": STORE, "reason": "armadora"}]),
    "reach_plan.capped_sellers": ([STORE, OTHER_STORE], [STORE]),
}


def _with(key, value):
    if key == "reach_plan.capped_sellers":
        return {"reach_plan": {"wide_part_indexes": [], "capped_sellers": value}}
    return {key: value}


def _value(part, key):
    if key == "reach_plan.capped_sellers":
        return part["reach_plan"]["capped_sellers"]
    return part[key]


@pytest.mark.parametrize("key", STORE_KEYS)
@pytest.mark.parametrize("store", [STORE, None])
def test_store_view_keeps_a_stored_none(key, store):
    assert _value(service.__store_view(_with(key, None), store), key) is None


@pytest.mark.parametrize("key", STORE_KEYS)
@pytest.mark.parametrize("store, expected", [(STORE, "own"), (None, [])])
def test_store_view_keeps_only_the_callers_own_entries(key, store, expected):
    stored, own = STORE_KEYS[key]
    assert _value(service.__store_view(_with(key, stored), store), key) == (own if expected == "own" else expected)


def test_store_view_leaves_an_absent_key_absent():
    assert service.__store_view({"part": {}}, STORE) == {"part": {}}


# Through the endpoints: the schema keeps these three on the part itself; a sister part in partList keeps all five.
SCHEMA_KEYS = ["subscribedSellers", "subscribedFollowers", "nonCompatibleSellers"]
VIEWERS = [("s1", STORE, "own"), ("s1", OTHER_STORE, []), (None, None, [])]  # seller, non-member, anonymous


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("key", SCHEMA_KEYS)
@pytest.mark.parametrize("uid, group, expected", VIEWERS)
def test_lists_keep_none_and_filter_lists_per_key(endpoint, key, uid, group, expected):
    stored, own = STORE_KEYS[key]
    body, parts = _read(endpoint, uid=uid, group=group, **{key: None})
    assert _live(body, parts)[key] is None
    body, parts = _read(endpoint, uid=uid, group=group, **{key: stored})
    assert _live(body, parts)[key] == (own if expected == "own" else expected)


@pytest.mark.parametrize("key", SCHEMA_KEYS)
@pytest.mark.parametrize("uid, group, expected", VIEWERS)
def test_get_by_id_keeps_none_and_filters_lists_per_key(key, uid, group, expected):
    from tests.test_offer_before_change import _live_part_with_offers

    stored, own = STORE_KEYS[key]
    assert _live_part_with_offers(uid=uid, group=group, **{key: None})[0][key] is None
    assert _live_part_with_offers(uid=uid, group=group, **{key: stored})[0][key] == (
        own if expected == "own" else expected)


@pytest.mark.parametrize("key", STORE_KEYS)
@pytest.mark.parametrize("uid, group, expected", VIEWERS)
def test_get_by_id_sister_parts_keep_none_and_filter_lists_per_key(key, uid, group, expected):
    from tests.test_offer_before_change import _live_part_with_offers

    stored, own = STORE_KEYS[key]
    sisters = [{"_id": ObjectId(), "part": {}, **_with(key, None)}, {"_id": ObjectId(), "part": {}, **_with(key, stored)}]
    body, _ = _live_part_with_offers(uid=uid, group=group, sisters=sisters)
    assert _value(body["partList"][0], key) is None
    assert _value(body["partList"][1], key) == (own if expected == "own" else expected)
