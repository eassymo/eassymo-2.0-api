"""pickup_code reaches only members of the selling group, only while the order waits for collection.
Buyers share GET /order with sellers, so membership (never the query parameter alone) decides."""
from datetime import datetime
from unittest.mock import patch

import pytest
from bson import ObjectId

import main
from app.services import OrderService, PickupCodeService
from tests.asgi_client import AsgiClient
from tests.test_pickup_code import FakeRepo

OID = ObjectId()
SELLER = "seller-group"
BUYER = "buyer-1"
MEMBERS = {SELLER: {"seller-uid", "both-uid"}, BUYER: {"buyer-uid", "both-uid"}}


def _doc(status="WAITING_FOR_COLLECTION"):
    return {
        "_id": OID, "order_id": "21-11-26-ab12", "creator_user": "buyer-user", "group": BUYER, "status": status,
        "offer": {"_id": "offer-1", "request_id": "req-1", "user_uid": "seller-uid", "group_id": SELLER,
                  "unit_of_measure": "Pieza", "internalComments": "", "publicComments": "",
                  "status": "Created", "type": "PartOffer", "price": 100.0},
        "part_request": {"_id": "req-1", "creatorGroup": BUYER, "creatorUser": "buyer-user", "vehicleId": "veh-1",
                         "isActive": True, "partList": [], "status": "Created", "subscribedSellers": [SELLER],
                         "part": {"tipoParteDescripcion": "Balata"},
                         "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow()},
        "status_history": [], "updated_at": datetime.utcnow(),
    }


@pytest.fixture
def env():
    repo = FakeRepo()
    store = {"doc": _doc()}
    with patch.object(PickupCodeService, "repo", repo), \
         patch.object(PickupCodeService, "_user_in_group", side_effect=lambda uid, gid: uid in MEMBERS.get(gid, set())), \
         patch.object(OrderService.orderRepository, "find", side_effect=lambda f: [dict(store["doc"])]), \
         patch.object(OrderService.orderRepository, "find_by_id", side_effect=lambda i: [dict(store["doc"])]):
        code = PickupCodeService.assign_code(str(OID))
        yield code, store


def _list(role, uid):
    group = SELLER if role == "2" else BUYER
    result = OrderService.find(None, group, role, None, requesting_user_uid=uid)
    return (result["sales"] if role == "2" else result["orders"])[0]


def test_selling_group_member_sees_pickup_code_while_waiting_for_collection(env):
    code, _ = env
    assert _list("2", "seller-uid")["pickup_code"] == code


def test_buyer_of_the_same_order_never_sees_it(env):
    assert "pickup_code" not in _list("1", "buyer-uid")


def test_a_member_of_both_groups_sees_it_only_in_the_seller_view(env):
    code, _ = env
    assert _list("2", "both-uid")["pickup_code"] == code
    assert "pickup_code" not in _list("1", "both-uid")


def test_a_non_member_asking_for_the_seller_list_gets_no_code(env):
    assert "pickup_code" not in _list("2", "buyer-uid")
    assert "pickup_code" not in _list("2", None)


def test_no_code_once_dispatched(env):
    _, store = env
    store["doc"] = _doc("DISPATCHED")
    assert "pickup_code" not in _list("2", "seller-uid")


def test_get_by_id_gives_the_code_only_to_the_selling_group(env):
    code, _ = env
    assert OrderService.find_by_id(str(OID), requesting_user_uid="seller-uid")["pickup_code"] == code
    assert "pickup_code" not in OrderService.find_by_id(str(OID), requesting_user_uid="buyer-uid")
    assert "pickup_code" not in OrderService.find_by_id(str(OID))


def test_order_json_itself_never_carries_the_code(env):
    from app.schemas.Order import Order
    assert "pickup_code" not in Order(**_doc()).toJson()


def test_routes_pass_the_caller_so_the_http_response_has_the_code_only_for_sellers(env):
    code, _ = env

    def as_user(uid):
        async def verify(request):
            request.state.user = {"uid": uid}
            request.state.groupSelected = SELLER
            return request.state.user
        return patch.object(main, "verify_token", side_effect=verify)

    with as_user("seller-uid"):
        mine = AsgiClient(main.app).get(f"/order/{OID}").json()["body"]
        listed = AsgiClient(main.app).get(f"/order?group_id={SELLER}&current_role=2").json()["body"]["sales"][0]
    with as_user("buyer-uid"):
        theirs = AsgiClient(main.app).get(f"/order/{OID}").json()["body"]
        theirs_list = AsgiClient(main.app).get(f"/order?group_id={BUYER}&current_role=1").json()["body"]["orders"][0]
    assert mine["pickup_code"] == code and listed["pickup_code"] == code
    assert "pickup_code" not in theirs and "pickup_code" not in theirs_list
