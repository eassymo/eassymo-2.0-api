"""What the rider's endpoints return: readiness and the store's contact, never the pickup code."""
from datetime import datetime
from unittest.mock import patch

import pytest
from bson import ObjectId

from app.services import DeliveryService as svc
from app.services import PickupCodeService
from tests.test_pickup_code import FakeRepo

OID = ObjectId()
TOKEN = "tok-1"
READY = datetime(2026, 11, 21, 21, 5)


def _doc(status):
    return {
        "_id": OID, "order_id": "21-11-26-ab12", "creator_user": "buyer-user", "group": "buyer-1", "status": status,
        "offer": {"_id": "offer-1", "request_id": "req-1", "user_uid": "seller-uid", "group_id": "seller-group",
                  "unit_of_measure": "Pieza", "internalComments": "", "publicComments": "",
                  "status": "Created", "type": "PartOffer", "price": 100.0},
        "offer_group": {"_id": "seller-group", "name": "Grimaldi", "phone": "9841234567", "address": "Cda. Ninguno 59"},
        "part_request": {"_id": "req-1", "creatorGroup": "buyer-1", "creatorUser": "buyer-user", "vehicleId": "veh-1",
                         "isActive": True, "partList": [], "status": "Created", "subscribedSellers": ["seller-group"],
                         "part": {"tipoParteDescripcion": "Balata"},
                         "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow()},
        "status_history": [], "updated_at": datetime.utcnow(), "ready_at": READY,
        "delivery_assignment": {"type": "guest", "guest_token": TOKEN, "guest_name": "Beto", "assigned_at": datetime.utcnow()},
    }


@pytest.fixture
def waiting():
    repo = FakeRepo()
    with patch.object(PickupCodeService, "repo", repo), \
         patch.object(svc.orderRepository, "find", return_value=[_doc("WAITING_FOR_COLLECTION")]):
        PickupCodeService.assign_code(str(OID))
        yield repo.find(str(OID))["code"]


def test_rider_payload_includes_ready_at_and_the_store_contact(waiting):
    order = svc._fetch_orders_for_delivery({"delivery_assignment.guest_token": TOKEN})[0]
    assert order["ready_at"] is not None and "2026-11-21" in order["ready_at"]
    assert order["offer_group"]["name"] == "Grimaldi"
    assert order["offer_group"]["address"] == "Cda. Ninguno 59"


def test_rider_payload_never_includes_pickup_code(waiting):
    order = svc._fetch_orders_for_delivery({"delivery_assignment.guest_token": TOKEN})[0]
    assert "pickup_code" not in order
    assert waiting not in str(order.get("pickup_code"))
    with patch.object(svc, "_resolve_active_guest_profile"), patch.object(svc, "_assert_guest_token_active"):
        mine = svc.get_guest_orders(TOKEN, None)[0]
        one = svc.get_guest_order_by_id(TOKEN, "21-11-26-ab12")
    assert "pickup_code" not in mine and "pickup_code" not in one


def test_account_rider_payload_has_no_code_either(waiting):
    with patch.object(svc, "_assert_has_delivery_role"):
        orders = svc.get_my_orders("rider-1", None)
    assert all("pickup_code" not in o for o in orders)


def test_a_rider_cannot_read_the_code_from_the_order_by_id(waiting):
    from app.services import OrderService
    with patch.object(OrderService.orderRepository, "find_by_id", return_value=[_doc("WAITING_FOR_COLLECTION")]), \
         patch.object(PickupCodeService, "_user_in_group", return_value=False):
        assert "pickup_code" not in OrderService.find_by_id(str(OID), requesting_user_uid="rider-1")


def test_rider_payload_says_whether_a_code_is_needed_without_giving_it(waiting):
    order = svc._fetch_orders_for_delivery({"delivery_assignment.guest_token": TOKEN})[0]
    assert order["pickup_code_required"] is True
    assert waiting not in str(order)


def test_orders_without_a_code_say_so_so_the_old_tap_still_works():
    repo = FakeRepo()
    with patch.object(PickupCodeService, "repo", repo), \
         patch.object(svc.orderRepository, "find", return_value=[_doc("WAITING_FOR_COLLECTION")]):
        order = svc._fetch_orders_for_delivery({"delivery_assignment.guest_token": TOKEN})[0]
    assert order["pickup_code_required"] is False


def test_the_flag_is_only_set_while_waiting_for_collection():
    with patch.object(svc.orderRepository, "find", return_value=[_doc("DISPATCHED")]):
        order = svc._fetch_orders_for_delivery({"delivery_assignment.guest_token": TOKEN})[0]
    assert "pickup_code_required" not in order
