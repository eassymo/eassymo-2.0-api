"""An offer the store withdrew (No_Inventory, e.g. it canceled the buyer's order) is not one the buyer can pick:
the buyer's offer lists leave it out. The seller's own screens still get it (they show it as "sin stock")."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bson import ObjectId

from app.services import OfferService as offer_service
from app.services import PartRequestService as service

SELLER = str(ObjectId())
CANCELED_SELLER = str(ObjectId())
BUYER = str(ObjectId())
REQ = str(ObjectId())


def _offer(group_id, brand, status):
    return {"_id": ObjectId(), "request_id": REQ, "group_id": group_id, "brand": brand, "price": 100, "status": status,
            "code": "", "guarantee": "", "unit_of_measure": "Pieza", "to_be_delivered_time": None,
            "user_uid": "u", "internalComments": "", "publicComments": ""}


LIVE = _offer(SELLER, "QUAKER", "Created")
WITHDRAWN = _offer(CANCELED_SELLER, "FRITEC", "No_Inventory")


def _matches(offer, filters):
    for key, want in filters.items():
        have = offer.get(key)
        if isinstance(want, dict):
            if "$ne" in want and have == want["$ne"]:
                return False
            if "$nin" in want and have in want["$nin"]:
                return False
        elif have != want:
            return False
    return True


def _attach(owner, status=None):
    def fake_find(filters):
        return [o for o in (LIVE, WITHDRAWN) if _matches(o, filters)]

    part = {"_id": ObjectId(REQ), "creatorGroup": BUYER, "creatorUser": "u", "vehicleId": "v", "status": "Created",
            "part": {"tipoParteDescripcion": "Aceite"}, "createdAt": "2026-11-24T10:00:00Z"}
    with patch.object(service.offerRepository, "find", side_effect=fake_find), \
         patch.object(service.listService, "get_followers_not_in_my_lists", return_value=[]), \
         patch.object(service.groupRepository, "find_by_id", return_value={"_id": ObjectId(SELLER), "name": "g"}), \
         patch.object(service, "GroupSchema", side_effect=lambda **kw: MagicMock(toJson=lambda: {"name": "g"})), \
         patch.object(service, "__check_if_group_is_favorite", return_value=False), \
         patch.object(service, "__check_if_group_is_in_non_favorite_list", return_value=False), \
         patch.object(service, "PartRequest", side_effect=lambda **kw: MagicMock(toJson=lambda: {"_id": str(kw["_id"])})):
        result = service.__attach_offers_to_part_requests([part], BUYER, "uid", [], status, owner)
    return [o["brand"] for o in result[0]["offers"]]


def test_buyer_offer_selector_leaves_out_the_canceled_stores_offer():
    assert _attach(owner=None) == ["QUAKER"]


def test_seller_still_sees_its_own_withdrawn_offer():
    assert _attach(owner=CANCELED_SELLER) == ["FRITEC"]


def test_asking_for_a_status_explicitly_is_honored():
    assert _attach(owner=None, status="No_Inventory") == ["FRITEC"]


def test_vehicle_view_passes_the_owner_group_through():
    request = SimpleNamespace(state=SimpleNamespace(_state={"user": {"uid": "uid"}}))
    cursor = MagicMock()
    cursor.sort.return_value.limit.return_value = []
    with patch("app.config.database.db", {"PartRequests": MagicMock(find=MagicMock(return_value=cursor))}), \
         patch.object(service, "__attach_offers_to_part_requests", return_value=[]) as attach:
        service.find_vehicle_requests_with_offers(request, "veh", BUYER, SELLER, None, [])
    assert attach.call_args.kwargs.get("offer_owner_group") == SELLER


def _offer_viewer(group_id):
    request = SimpleNamespace(state=SimpleNamespace(_state={"user": {"uid": "uid"}}))
    part = MagicMock(creatorGroup=BUYER)
    group = MagicMock(id=group_id, type=1)
    with patch.object(offer_service.partRequestRepository, "find_by_id", return_value=[{"_id": REQ}]), \
         patch.object(offer_service, "PartRequest", return_value=part), \
         patch.object(offer_service.groupRepository, "find_by_id", return_value=None), \
         patch.object(offer_service.listService, "get_followers_list", return_value=[]), \
         patch.object(offer_service, "GroupSchema", return_value=group), \
         patch.object(offer_service, "_group_acts_as_callcenter", return_value=False), \
         patch.object(offer_service.offerRepository, "find_by_request_id_and_group",
                      side_effect=lambda rid, gids, cc: [dict(o) for o in (LIVE, WITHDRAWN)
                                                         if not gids or o["group_id"] in gids]), \
         patch.object(offer_service.groupRepository, "find_by_id", side_effect=[{"name": "g"}, None, None]):
        return [o["brand"] for o in offer_service.find_by_request_id_and_group(request, REQ, group_id)]


def test_buyer_offer_viewer_leaves_out_the_canceled_stores_offer():
    assert _offer_viewer(BUYER) == ["QUAKER"]


def test_seller_offer_form_still_gets_its_withdrawn_offer():
    assert _offer_viewer(CANCELED_SELLER) == ["FRITEC"]
