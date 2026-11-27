"""After the buyer changes or removes a part, the store sees it in its cotizador: it can say its offer still stands
(POST /offer/{id}/confirm-current) or edit it (both clear `before_change`), and its request payload carries the change,
the removal and the offers it lost to the removal. Removed parts it never quoted are left out for that store."""
from datetime import datetime, timezone
from unittest.mock import ANY, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import FastAPI

from app.authz import grant_keys as g
from app.repositories import OfferRepository as offerRepositoryModule
from app.routers import OfferRouter as router_mod
from app.schemas.Offer import Offer
from app.services import OfferChangeService, OfferService
from app.services import PartRequestService as service
from app.services import authz
from tests.asgi_client import AsgiClient

OID = "64b7f0f0f0f0f0f0f0f0f0f0"
STORE = str(ObjectId())
OTHER_STORE = str(ObjectId())
BUYER = str(ObjectId())
CHANGED_AT = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
REMOVED_AT = datetime(2026, 11, 27, 11, 0, tzinfo=timezone.utc)


# --- POST /offer/{id}/confirm-current ---------------------------------------------------------------------------

def _stored_offer(group_id=STORE):
    return {"_id": ObjectId(OID), "request_id": "r1", "group_id": group_id, "status": "Created",
            "before_change": True, "price": 185.0}


@pytest.fixture
def confirm_env():
    app = FastAPI()
    app.include_router(router_mod.offerRouter)
    grants = {"set": {g.OFFERS_EDIT}}
    acting = {"group": STORE}
    offers = MagicMock()
    offers.find_one.return_value = _stored_offer()
    offers.update_one.return_value = MagicMock(matched_count=1)
    db = MagicMock()
    db.db = {"Offers": offers}
    with patch.object(authz, "caller_uid", return_value="store-uid"), \
         patch.object(authz, "selected_group", side_effect=lambda *a, **k: acting["group"]), \
         patch.object(authz, "effective_grants", side_effect=lambda *a, **k: frozenset(grants["set"])), \
         patch.object(offerRepositoryModule, "database", db), \
         patch.object(OfferChangeService.OfferWithdrawalService, "_user_in_group", return_value=True):
        yield AsgiClient(app), offers, grants, acting


def test_confirm_current_clears_flag(confirm_env):
    client, offers, _, _ = confirm_env
    r = client.post(f"/offer/{OID}/confirm-current")
    assert r.status_code == 200
    assert r.json()["body"] == {"offer_id": OID, "before_change": False}
    offers.update_one.assert_called_once_with(
        {"_id": ObjectId(OID)}, {"$set": {"before_change": False, "confirmed_current_at": ANY}})
    at = offers.update_one.call_args.args[1]["$set"]["confirmed_current_at"]
    assert isinstance(at, datetime) and at.tzinfo is not None


def test_confirm_current_other_store_403(confirm_env):
    client, offers, _, acting = confirm_env
    acting["group"] = OTHER_STORE
    r = client.post(f"/offer/{OID}/confirm-current")
    assert r.status_code == 403
    assert "Solo la tienda que cotizó puede cambiarla." in r.text
    offers.update_one.assert_not_called()


def test_confirm_current_gone_offer_404(confirm_env):
    client, offers, _, _ = confirm_env
    offers.find_one.return_value = None
    r = client.post(f"/offer/{OID}/confirm-current")
    assert r.status_code == 404 and "Esta opción ya no existe." in r.text
    offers.update_one.assert_not_called()


def test_confirm_current_offer_archived_meanwhile_404(confirm_env):
    client, offers, _, _ = confirm_env
    offers.update_one.return_value = MagicMock(matched_count=0)
    r = client.post(f"/offer/{OID}/confirm-current")
    assert r.status_code == 404 and "Esta opción ya no existe." in r.text


def test_confirm_current_without_offers_edit_403(confirm_env):
    client, offers, grants, _ = confirm_env
    grants["set"] = set()
    assert client.post(f"/offer/{OID}/confirm-current").status_code == 403
    offers.find_one.assert_not_called()
    offers.update_one.assert_not_called()


# --- PUT /offer/edit-offer/{id} -----------------------------------------------------------------------------------

def test_edit_offer_clears_flag():
    payload = Offer(request_id="r1", user_uid="u1", group_id=STORE, unit_of_measure="Pieza", price=190.0,
                    brand="FRITEC", guarantee="6 meses", internalComments="", publicComments="")
    written = {}

    def fake_edit(offer_uid, data):
        written.update(data)
        return {"_id": ObjectId(OID), **data}

    with patch.object(OfferService.offerRepository, "edit_offer", side_effect=fake_edit), \
         patch.object(OfferService.brandService, "insert"), \
         patch.object(OfferService.guaranteeService, "insert"):
        result = OfferService.edit_offer(OID, payload)
    assert written["before_change"] is False
    assert result["before_change"] is False


# --- seller read model (GET /partRequest/sibling-requests-with-offers?offer_owner_group=…) -------------------------

def _part(**extra):
    return {"_id": ObjectId(), "creatorGroup": BUYER, "creatorUser": "b1", "vehicleId": "v", "status": "Created",
            "part": {"tipoParteDescripcion": "Faro"}, "subscribedSellers": [STORE, OTHER_STORE],
            "createdAt": "2026-11-27T09:00:00Z", **extra}


def _offer(request_id, group_id, price, **extra):
    return {"_id": ObjectId(), "request_id": request_id, "group_id": group_id, "brand": "FRITEC", "price": price,
            "status": "Created", "code": "", "guarantee": "", "unit_of_measure": "Pieza",
            "to_be_delivered_time": None, "user_uid": "u", "internalComments": "", "publicComments": "", **extra}


def _archived(request_id, group_id, price, reason="part_removed"):
    return {**_offer(request_id, group_id, price),
            "discard": {"by": "b1", "at": REMOVED_AT, "reason": reason, "previous_status": "Created"}}


def _matches(doc, filters):
    return all(doc.get(k) == v if "." not in k else
               (doc.get(k.split(".")[0]) or {}).get(k.split(".")[1]) == v
               for k, v in filters.items() if not isinstance(v, dict))


def _attach(parts, live, archived, owner=STORE, skip_removed=True):
    group = {"_id": ObjectId(STORE), "name": "Mi tienda", "type": 2}
    with patch.object(service.offerRepository, "find", side_effect=lambda f: [o for o in live if _matches(o, f)]), \
         patch.object(service.offerArchiveRepository, "find",
                      side_effect=lambda f: [o for o in archived if _matches(o, f)]), \
         patch.object(service.listService, "get_followers_not_in_my_lists", return_value=[]), \
         patch.object(service.groupRepository, "find_by_id", return_value=group), \
         patch.object(service, "GroupSchema", side_effect=lambda **kw: MagicMock(toJson=lambda: {"name": "g"})), \
         patch.object(service, "__check_if_group_is_favorite", return_value=False), \
         patch.object(service, "__check_if_group_is_in_non_favorite_list", return_value=False):
        return service.__attach_offers_to_part_requests(parts, BUYER, "uid", [], None, owner, skip_removed=skip_removed)


def test_seller_sees_removed_part_with_its_discarded_offer():
    active = _part()
    removed = _part(isActive=False, removed={"by": "b1", "at": REMOVED_AT})
    rid = str(removed["_id"])
    archived = [
        _archived(rid, STORE, 185),
        _archived(rid, STORE, 185),
        _archived(rid, STORE, 240.5),
        _archived(rid, OTHER_STORE, 99),               # another store's offer: not this store's loss
        _archived(rid, STORE, 50, reason="withdrawn"),  # not discarded by the removal
    ]
    result = _attach([active, removed], [_offer(str(active["_id"]), STORE, 300)], archived)

    by_id = {p["_id"]: p for p in result}
    assert set(by_id) == {str(active["_id"]), rid}
    gone = by_id[rid]
    assert gone["removed"] == {"at": "2026-11-27T11:00:00.000Z"}  # never the buyer's uid
    assert gone["offers"] == []
    assert gone["discarded_offers"] == [{"price": 185.0, "count": 2}, {"price": 240.5, "count": 1}]
    assert all(isinstance(d["price"], float) for d in gone["discarded_offers"])

    # Active parts keep every existing field and filter; they just say they were not removed.
    kept = by_id[str(active["_id"])]
    assert kept["removed"] is None
    assert "discarded_offers" not in kept
    assert [o["price"] for o in kept["offers"]] == [300]


def test_seller_without_offer_does_not_see_removed_part():
    active = _part()
    removed = _part(isActive=False, removed={"by": "b1", "at": REMOVED_AT})
    rid = str(removed["_id"])
    result = _attach([active, removed], [], [_archived(rid, OTHER_STORE, 99)])
    assert [p["_id"] for p in result] == [str(active["_id"])]


def test_buyer_view_leaves_out_removed_parts():
    active = _part()
    removed = _part(isActive=False, removed={"by": "b1", "at": REMOVED_AT})
    result = _attach([active, removed], [], [], owner=None)
    assert [p["_id"] for p in result] == [str(active["_id"])]


def test_buyer_single_part_read_still_enriches_a_removed_part():
    removed = _part(isActive=False, removed={"by": "b1", "at": REMOVED_AT})
    result = _attach([removed], [], [], owner=None, skip_removed=False)
    assert len(result) == 1 and result[0]["removed"] == {"by": "b1", "at": "2026-11-27T11:00:00.000Z"}


def test_sibling_and_vehicle_lists_skip_removed_parts_for_the_buyer():
    with patch.object(service, "__attach_offers_to_part_requests", return_value=[]) as attach, \
         patch.object(service, "_viewer", return_value=("u1", BUYER, True)), \
         patch("app.config.database") as db:
        db.db.__getitem__.return_value.aggregate.return_value = []
        db.db.__getitem__.return_value.find.return_value.sort.return_value.limit.return_value = []
        request = MagicMock()
        request.state._state = {"user": {"uid": "u1"}}
        service.find_vehicle_requests_with_offers(request, "v", BUYER, None, None, [])
    assert attach.call_args.kwargs.get("skip_removed") is True

    newest = {**_part(), "createdAtDate": datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc),
              "vehicleInformation": None}
    with patch.object(service, "__attach_offers_to_part_requests", return_value=[]) as attach, \
         patch.object(service, "_viewer", return_value=("u1", BUYER, True)), \
         patch.object(service, "PartRequest", return_value=MagicMock(creatorGroup=BUYER)), \
         patch("app.config.database") as db:
        db.db.__getitem__.return_value.aggregate.return_value = [newest]
        request = MagicMock()
        request.state._state = {"user": {"uid": "u1"}}
        service.find_sibling_requests_with_offers(request, "p1", None, None, [])
    assert attach.call_args.kwargs.get("skip_removed") is True


def test_buyer_payload_keeps_who_changed_the_part():
    change = {"at": CHANGED_AT, "by": "b1", "fields": [{"field": "position", "before": "A", "after": "B"}]}
    result = _attach([_part(last_change=change)], [], [], owner=None)
    assert result[0]["last_change"]["by"] == "b1"


def test_seller_payload_carries_last_change():
    change = {"at": CHANGED_AT, "by": "b1",
              "fields": [{"field": "position", "before": "Izquierda", "after": "Derecha"}]}
    changed = _part(last_change=change)
    plain = _part()
    live = [_offer(str(changed["_id"]), STORE, 185, before_change=True, before_change_at=CHANGED_AT),
            _offer(str(plain["_id"]), STORE, 90)]
    result = _attach([changed, plain], live, [])

    by_id = {p["_id"]: p for p in result}
    assert by_id[str(changed["_id"])]["last_change"] == {  # never the buyer's uid
        "at": "2026-11-27T10:00:00.000Z",
        "fields": [{"field": "position", "before": "Izquierda", "after": "Derecha"}]}
    assert by_id[str(plain["_id"])]["last_change"] is None
    assert by_id[str(changed["_id"])]["offers"][0]["before_change"] is True
    assert by_id[str(plain["_id"])]["offers"][0]["before_change"] is False


# --- GET /offer/find_by_request_id_and_group (the buyer's /offer-viewer/[id]) ---------------------------------------

def test_offer_viewer_payload_carries_before_change():
    from tests.test_offer_withdrawal_guards import _seller_list
    from tests.test_withdrawn_offers_hidden_from_buyer import _offer as _viewer_offer, SELLER as VIEWER_SELLER
    flagged = {**_viewer_offer(VIEWER_SELLER, "BOSCH", "Created"), "before_change": True}
    plain = _viewer_offer(VIEWER_SELLER, "MONROE", "Created")
    result = _seller_list([flagged, plain], None)
    assert [o["before_change"] for o in result] == [True, False]


# --- GET /partRequest/{id} for a removed part (the PART_REMOVED notice's link, buyer deep links) ---------------------

GET_MEMBERS = dict(
    groups={BUYER: {"users": ["u1", "both-1"], "owner": "owner-1"}, STORE: {"users": ["s1", "both-1"]},
            OTHER_STORE: {"users": ["o1"]}},
    users={"listed-1": {"groups": [BUYER]}},
    roles=[("role-1", BUYER), ("seller-role-1", STORE)],
)


def _get_by_id(uid="u1", group=BUYER, offers=(), archived=(), sisters=(), rid=None, **extra):
    """GET /partRequest/{id} as `uid` (None: no signed-in user) acting for `group` (the GroupSelected header; None: no
    header). Membership is the real check, on GET_MEMBERS (tests/test_part_removal.py `store_members`)."""
    from tests.test_part_removal import store_members
    from app.routers import PartRequestRouter as pr_router
    rid = rid or ObjectId()
    doc = {**_part(isActive=False, removed={"by": "b1", "at": REMOVED_AT}), "_id": rid,
           "createdAt": "2026-11-27T09:00:00Z", "updatedAt": "2026-11-27T11:00:00Z", "specific_order_uid": "so-1",
           "vehicleInformation": {"year": "2018", "maker": "Nissan", "model": "Versa", "group": BUYER, "user": "b1",
                                  "subModel": "Sense"},
           "group_info": {}, **extra}
    app = FastAPI()

    @app.middleware("http")
    async def signed_in(request, call_next):
        if uid:
            request.state.user = {"uid": uid}
        return await call_next(request)

    app.include_router(pr_router.partRequestRouter)
    group_doc = {"_id": ObjectId(STORE), "name": "Mi tienda", "type": 2}
    with patch.object(service.partRequestRepository, "find_by_id", return_value=[doc]), \
         patch.object(service.partRequestRepository, "find_sister_part_requests", return_value=list(sisters)), \
         patch.object(service.offerRepository, "find", side_effect=lambda f: [o for o in offers if _matches(o, f)]), \
         patch.object(service.offerArchiveRepository, "find",
                      side_effect=lambda f: [o for o in archived if _matches(o, f)]), \
         patch.object(service.listService, "get_followers_not_in_my_lists", return_value=[]), \
         patch.object(service.groupRepository, "find_by_id", return_value=group_doc), \
         patch.object(service, "GroupSchema", side_effect=lambda **kw: MagicMock(toJson=lambda: {"name": "g"})), \
         patch.object(service, "__check_if_group_is_favorite", return_value=False), \
         patch.object(service, "__check_if_group_is_in_non_favorite_list", return_value=False), \
         store_members(**GET_MEMBERS):
        r = AsgiClient(app).get(f"/partRequest/{rid}", headers={"GroupSelected": group} if group else None)
    assert r.status_code == 200, r.text
    return r.json()["body"]


CHANGE = {"by": "b1", "at": CHANGED_AT, "fields": []}


def test_get_removed_part_by_id_is_200_with_removed_serialized():
    body = _get_by_id(last_change=CHANGE)
    assert body["removed"] == {"by": "b1", "at": "2026-11-27T11:00:00.000Z"}
    assert body["last_change"]["by"] == "b1"


def test_get_by_id_never_tells_a_seller_who():
    body = _get_by_id(uid="s1", group=STORE, last_change=CHANGE)
    assert body["removed"] == {"at": "2026-11-27T11:00:00.000Z"}
    assert body["last_change"] == {"at": "2026-11-27T10:00:00.000Z", "fields": []}


def test_find_by_id_without_a_caller_strips_who_from_every_record():
    """No signed-in caller (or one outside the buyer's store): no `by` anywhere, change_log and sister parts too, and
    no offers."""
    doc = {**_part(last_change={"by": "b1", "at": CHANGED_AT, "fields": []},
                   removed={"by": "b1", "at": REMOVED_AT},
                   change_log=[{"by": "b1", "at": CHANGED_AT, "fields": []}, {"by": "b2", "at": CHANGED_AT}],
                   offers=[{"group_id": STORE}]),
           "updatedAt": "2026-11-27T11:00:00Z", "specific_order_uid": "so-1",
           "vehicleInformation": {}, "group_info": {}}
    sister = {"_id": ObjectId(), "part": {}, "last_change": {"by": "b1", "at": CHANGED_AT}}
    with patch.object(service.partRequestRepository, "find_by_id", return_value=[doc]), \
         patch.object(service.partRequestRepository, "find_sister_part_requests", return_value=[sister]), \
         patch.object(service.offerRepository, "find", return_value=[]):
        found = service.find_by_id(str(doc["_id"]), None)
    assert found["last_change"] == {"at": "2026-11-27T10:00:00.000Z", "fields": []}
    assert found["removed"] == {"at": "2026-11-27T11:00:00.000Z"}
    assert [entry.get("by") for entry in found["change_log"]] == [None, None]
    assert "by" not in found["partList"][0]["last_change"]
    assert found["offers"] == []


@pytest.mark.parametrize("uid", ["u1", "owner-1", "listed-1", "role-1"])
def test_get_by_id_tells_any_buyer_member_who(uid):
    """Owner, the user's own groups list, an active role: the same membership require_grant uses."""
    body = _get_by_id(uid=uid, last_change=CHANGE)
    assert body["removed"]["by"] == "b1"
    assert body["last_change"]["by"] == "b1"


@pytest.mark.parametrize("uid", ["s1", "seller-role-1"])
def test_get_by_id_hides_who_from_a_seller_with_the_real_check(uid):
    body = _get_by_id(uid=uid, group=STORE, last_change=CHANGE)
    assert "by" not in body["removed"] and "by" not in body["last_change"]


# --- GET /partRequest/{id}: which offers each caller sees ------------------------------------------------------------

def _live_part_with_offers(**kw):
    rid = ObjectId()
    offers = [_offer(str(rid), STORE, 300), _offer(str(rid), OTHER_STORE, 280), _offer(str(rid), STORE, 310)]
    body = _get_by_id(rid=rid, offers=offers, isActive=True, removed=None, **kw)
    return body, offers


def _offer_groups(body):
    return sorted(o["group_id"] for o in body["offers"])


@pytest.mark.parametrize("uid", ["u1", "role-1"])
def test_buyer_sees_every_offer(uid):
    body, _ = _live_part_with_offers(uid=uid)
    assert _offer_groups(body) == sorted([STORE, OTHER_STORE, STORE])


@pytest.mark.parametrize("uid", ["s1", "seller-role-1"])
def test_seller_sees_only_its_own_offers(uid):
    body, offers = _live_part_with_offers(uid=uid, group=STORE)
    assert _offer_groups(body) == [STORE, STORE]
    assert sorted(o["_id"] for o in body["offers"]) == sorted(str(o["_id"]) for o in offers if o["group_id"] == STORE)


def test_member_of_both_stores_acting_as_seller_sees_only_that_store():
    """The selected store decides, not every store the user belongs to."""
    body, _ = _live_part_with_offers(uid="both-1", group=STORE)
    assert _offer_groups(body) == [STORE, STORE]
    assert "by" not in (body.get("last_change") or {})


@pytest.mark.parametrize("uid, group", [
    ("s1", OTHER_STORE),  # selected a store it doesn't belong to
    ("u1", STORE),  # a buyer member claiming a seller store
    ("u1", None),  # no selected store
    (None, None),  # anonymous
    (None, STORE),
])
def test_caller_without_a_store_of_its_own_sees_no_offers(uid, group):
    body, _ = _live_part_with_offers(uid=uid, group=group, last_change=CHANGE)
    assert body["offers"] == []
    assert "by" not in body["last_change"]


def test_sister_parts_never_carry_offers_to_a_seller():
    sister = {"_id": ObjectId(), "part": {}, "offers": [{"group_id": OTHER_STORE}]}
    body, _ = _live_part_with_offers(uid="s1", group=STORE, sisters=[sister])
    assert "offers" not in body["partList"][0]


def test_seller_reading_a_removed_part_gets_what_it_lost():
    rid = ObjectId()
    archived = [_archived(str(rid), STORE, 185), _archived(str(rid), OTHER_STORE, 200)]
    body = _get_by_id(uid="s1", group=STORE, rid=rid, archived=archived)
    assert body["discarded_offers"] == [{"price": 185.0, "count": 1}]
    assert body["offers"] == []
    assert body["removed"] == {"at": "2026-11-27T11:00:00.000Z"}


# --- GET /partRequest/{id}: a stored doc with dates always serializes; other stores' entries stay hidden -------------

STORED_DATES = dict(
    last_reminder_at=datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc),
    last_widened_at=datetime(2026, 11, 27, 12, 30, tzinfo=timezone.utc),
    last_cancellation={"order_id": "o1", "store_group_id": OTHER_STORE, "store_name": "Otra", "reason": "no_stock",
                       "note": "", "at": datetime(2026, 11, 27, 13, 0, tzinfo=timezone.utc)},
    change_log=[{"by": "b1", "at": CHANGED_AT, "fields": []}],
    removing={"by": "b1", "at": REMOVED_AT},
)


@pytest.mark.parametrize("uid, group", [
    ("s1", STORE),  # a store that never quoted the removed part: no seller enrichment
    ("u1", None),  # the buyer without a selected store
    ("s1", OTHER_STORE),  # a store it doesn't belong to
    (None, None),  # anonymous
])
def test_unenriched_read_of_a_stored_doc_with_dates_is_200(uid, group):
    body = _get_by_id(uid=uid, group=group, last_change=CHANGE, **STORED_DATES)
    assert body["last_reminder_at"] == "2026-11-27T12:00:00.000Z"
    assert body["last_widened_at"] == "2026-11-27T12:30:00.000Z"
    assert body["offers"] == []
    assert "removing" not in body and "change_log" not in body
    assert "b1" not in str({k: v for k, v in body.items() if k not in ("creatorUser", "vehicleInformation")})


NON_COMPATIBLE = [{"group_id": STORE, "reason": "armadora"}, {"group_id": OTHER_STORE, "reason": "sistemas"}]


def _sellers_view(**kw):
    body, _ = _live_part_with_offers(nonCompatibleSellers=NON_COMPATIBLE, capped_sellers=[STORE, OTHER_STORE], **kw)
    return body


def test_buyer_sees_every_store_entry():
    body = _sellers_view(last_cancellation=STORED_DATES["last_cancellation"])
    assert sorted(body["subscribedSellers"]) == sorted([STORE, OTHER_STORE])
    assert [s["group_id"] for s in body["nonCompatibleSellers"]] == [STORE, OTHER_STORE]
    assert body["last_cancellation"]["store_group_id"] == OTHER_STORE


@pytest.mark.parametrize("uid", ["s1", "seller-role-1"])
def test_seller_sees_only_its_own_entries(uid):
    body = _sellers_view(uid=uid, group=STORE)
    assert body["subscribedSellers"] == [STORE]
    assert body["nonCompatibleSellers"] == [{"group_id": STORE, "reason": "armadora"}]
    assert body.get("capped_sellers") in (None, [STORE])


def test_seller_sees_its_own_cancellation_but_not_another_stores():
    own = {**STORED_DATES["last_cancellation"], "store_group_id": STORE}
    assert _sellers_view(uid="s1", group=STORE, last_cancellation=own)["last_cancellation"]["order_id"] == "o1"
    assert _sellers_view(uid="s1", group=STORE, last_cancellation=STORED_DATES["last_cancellation"]
                         )["last_cancellation"] is None


@pytest.mark.parametrize("uid, group", [(None, None), (None, STORE), ("s1", OTHER_STORE), ("u1", None)])
def test_caller_without_a_store_of_its_own_sees_no_store_entries(uid, group):
    body = _sellers_view(uid=uid, group=group, last_cancellation={**STORED_DATES["last_cancellation"],
                                                                  "store_group_id": STORE})
    assert body["subscribedSellers"] == []
    assert body["nonCompatibleSellers"] == []
    assert body.get("capped_sellers") in (None, [])
    assert body["last_cancellation"] is None


def test_sister_parts_carry_only_the_sellers_own_entries():
    sister = {"_id": ObjectId(), "part": {}, "subscribedSellers": [STORE, OTHER_STORE],
              "last_cancellation": {"store_group_id": OTHER_STORE}}
    body, _ = _live_part_with_offers(uid="s1", group=STORE, sisters=[sister])
    assert body["partList"][0]["subscribedSellers"] == [STORE]
    assert body["partList"][0]["last_cancellation"] is None
