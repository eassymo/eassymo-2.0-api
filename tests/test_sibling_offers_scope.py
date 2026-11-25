"""GET /partRequest/sibling-requests-with-offers: with offer_owner_group the seller gets only
that group's offers on each part, never another seller's brand and price."""
from unittest.mock import MagicMock, patch

from bson import ObjectId

from app.services import PartRequestService as service

MINE = str(ObjectId())
OTHER = str(ObjectId())
BUYER = str(ObjectId())
REQ = str(ObjectId())


def _offer(group_id, brand, status):
    return {"_id": ObjectId(), "request_id": REQ, "group_id": group_id, "brand": brand, "price": 100, "status": status,
            "code": "", "guarantee": "", "unit_of_measure": "Pieza", "to_be_delivered_time": None,
            "user_uid": "u", "internalComments": "", "publicComments": ""}


def _attach(owner):
    mine = _offer(MINE, "FRITEC", "Pending_Changes")
    other = _offer(OTHER, "QUAKER", "Created")
    seen = {}

    def fake_find(filters):
        seen["filters"] = filters
        rows = [mine, other]
        if filters.get("group_id"):
            rows = [o for o in rows if o["group_id"] == filters["group_id"]]
        return rows

    part = {"_id": ObjectId(REQ), "creatorGroup": BUYER, "creatorUser": "u", "vehicleId": "v", "status": "Created",
            "part": {"tipoParteDescripcion": "Aceite"}, "createdAt": "2026-11-24T10:00:00Z"}
    group = {"_id": ObjectId(MINE), "name": "Mi tienda", "type": 2}
    with patch.object(service.offerRepository, "find", side_effect=fake_find), \
         patch.object(service.listService, "get_followers_not_in_my_lists", return_value=[]), \
         patch.object(service.groupRepository, "find_by_id", return_value=group), \
         patch.object(service, "GroupSchema", side_effect=lambda **kw: MagicMock(toJson=lambda: {"name": "g"})), \
         patch.object(service, "__check_if_group_is_favorite", return_value=False), \
         patch.object(service, "__check_if_group_is_in_non_favorite_list", return_value=False), \
         patch.object(service, "PartRequest", side_effect=lambda **kw: MagicMock(toJson=lambda: {"_id": str(kw["_id"])})):
        result = service.__attach_offers_to_part_requests([part], BUYER, "uid", [], "Created", owner)
    return result, seen["filters"]


def test_owner_group_limits_the_offers_to_that_group():
    result, filters = _attach(MINE)
    assert filters["group_id"] == MINE
    assert [o["brand"] for o in result[0]["offers"]] == ["FRITEC"]


def test_without_an_owner_group_every_offer_is_returned_as_before():
    result, filters = _attach(None)
    assert "group_id" not in filters
    assert {o["brand"] for o in result[0]["offers"]} == {"FRITEC", "QUAKER"}
