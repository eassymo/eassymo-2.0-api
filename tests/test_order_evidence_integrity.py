"""Completing a delivery (or any status change) must never erase evidence the store, the rider
or the buyer already left. Pickup evidence has its own fields so it never shares one with the
delivery photos."""
from datetime import datetime
from unittest.mock import patch

import pytest
from bson import ObjectId

from app.services import DeliveryService, OrderService

OID = ObjectId()
TOKEN = "guest-token-1"


def _doc(**extra):
    doc = {
        "_id": OID,
        "order_id": "21-11-26-ab12",
        "creator_user": "buyer-user",
        "group": "buyer-1",
        "status": "DISPATCHED",
        "offer": {
            "_id": "offer-1", "request_id": "req-1", "user_uid": "seller-uid", "group_id": "seller-group",
            "unit_of_measure": "Pieza", "internalComments": "", "publicComments": "",
            "status": "Created", "type": "PartOffer", "price": 100.0,
        },
        "part_request": {
            "_id": "req-1", "creatorGroup": "buyer-1", "creatorUser": "buyer-user", "vehicleId": "veh-1",
            "isActive": True, "partList": [], "status": "Created", "subscribedSellers": ["seller-group"],
            "part": {"tipoParteDescripcion": "Balata"},
            "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow(),
        },
        "status_history": [],
        "updated_at": datetime.utcnow(),
        "packaged_notes_seller": "Caja sellada",
        "packaged_pictures_seller": ["store-1.jpg", "store-2.jpg"],
        "pickup_notes_seller": "Recogido con la caja cerrada",
        "pickup_pictures_seller": ["pickup-1.jpg"],
        "delivery_assignment": {"type": "guest", "guest_token": TOKEN, "guest_name": "Beto", "assigned_at": datetime.utcnow()},
    }
    doc.update(extra)
    return doc


@pytest.fixture
def saved():
    store = {}

    def edit(_id, data, **kw):
        store.clear()
        store.update(data)
        return {**data, "_id": _id}

    return store, edit


def _complete(doc, edit, **kw):
    args = dict(
        delivery_notes_buyer=None, delivery_notes_seller=None, packaged_notes_seller=None,
        delivery_customer_signature_url="https://x/sig.png", delivery_received_by_name="Ana Ruiz",
        delivery_pictures_seller=["drop.jpg"], enforce_delivery_completion_proof=True,
    )
    args.update(kw)
    with patch.object(OrderService.orderRepository, "find_by_id", return_value=[doc]), \
         patch.object(OrderService.orderRepository, "edit", side_effect=edit), \
         patch.object(OrderService, "_assert_order_status_transition"), \
         patch.object(OrderService, "_send_delivery_alert"), \
         patch("app.services.notification_fanout.fanout_order_status_change"):
        return OrderService.change_order_status(str(OID), "RECIEVED", **args)


def test_completing_a_delivery_keeps_packaged_notes_and_photos(saved):
    store, edit = saved
    _complete(_doc(), edit)
    assert store["packaged_notes_seller"] == "Caja sellada"
    assert store["packaged_pictures_seller"] == ["store-1.jpg", "store-2.jpg"]


def test_completing_a_delivery_keeps_pickup_notes_and_photos(saved):
    store, edit = saved
    _complete(_doc(), edit)
    assert store["pickup_notes_seller"] == "Recogido con la caja cerrada"
    assert store["pickup_pictures_seller"] == ["pickup-1.jpg"]


def test_delivery_photos_and_signature_are_stored(saved):
    store, edit = saved
    _complete(_doc(), edit)
    assert store["delivery_pictures_seller"] == ["drop.jpg"]
    assert store["delivery_customer_signature_url"] == "https://x/sig.png"
    assert store["delivery_received_by_name"] == "Ana Ruiz"
    assert store["status"] == "RECIEVED"


def test_an_explicit_empty_list_still_clears_a_field_when_the_caller_sends_it(saved):
    store, edit = saved
    _complete(_doc(), edit, packaged_pictures_seller=[], packaged_notes_seller="")
    assert store["packaged_pictures_seller"] == []
    assert store["packaged_notes_seller"] == ""


def test_buyer_receive_evidence_does_not_touch_seller_evidence(saved):
    store, edit = saved
    doc = _doc(delivery_pictures_seller=["drop.jpg"], delivery_notes_seller="Entregado",
               delivery_customer_signature_url="https://x/sig.png", delivery_received_by_name="Ana")
    with patch.object(OrderService.orderRepository, "find_by_id", return_value=[doc]), \
         patch.object(OrderService.orderRepository, "edit", side_effect=edit), \
         patch.object(OrderService, "_assert_order_status_transition"), \
         patch("app.services.notification_fanout.fanout_order_status_change"):
        OrderService.change_order_status(
            str(OID), "RECIEVED", "Llegó bien", None, None,
            delivery_pictures_buyer=["buyer-1.jpg"],
        )
    assert store["delivery_notes_buyer"] == "Llegó bien"
    assert store["delivery_pictures_buyer"] == ["buyer-1.jpg"]
    assert store["delivery_pictures_seller"] == ["drop.jpg"]
    assert store["delivery_notes_seller"] == "Entregado"
    assert store["packaged_pictures_seller"] == ["store-1.jpg", "store-2.jpg"]


def test_confirm_pickup_writes_pickup_fields_and_leaves_delivery_alone(saved):
    store, edit = saved
    doc = _doc(status="WAITING_FOR_COLLECTION", pickup_notes_seller=None, pickup_pictures_seller=[],
               delivery_pictures_seller=["earlier-drop.jpg"], delivery_notes_seller="earlier")
    with patch.object(DeliveryService, "require_active_guest"), \
         patch.object(DeliveryService.orderRepository, "find_one", return_value=doc), \
         patch.object(DeliveryService.orderRepository, "edit", side_effect=edit), \
         patch("app.services.notification_fanout.fanout_order_status_change"), \
         patch("app.services.PickupCodeService.has_code", return_value=False):
        DeliveryService.confirm_pickup(str(OID), guest_token=TOKEN, notes="Foto al recoger", photo_urls=["pickup-new.jpg"])
    assert store["pickup_notes_seller"] == "Foto al recoger"
    assert store["pickup_pictures_seller"] == ["pickup-new.jpg"]
    assert store["delivery_pictures_seller"] == ["earlier-drop.jpg"]
    assert store["delivery_notes_seller"] == "earlier"
    assert store["status"] == "DISPATCHED"
