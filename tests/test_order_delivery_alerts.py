"""OrderService sends delivery alerts on assign / reassign / time change / cancel,
and a failing alert never fails the order operation."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from bson import ObjectId

from app.schemas.Order import DeliveryAssignment, DeliveryAssignmentType
from app.services import DeliveryService, OrderService, notification_fanout

OID = ObjectId()
SELLER = "seller-group"


def _doc(status="READY_TO_BE_DISPATCHED", assignment=None, when=datetime(2026, 11, 19, 20, 0)):
    return {
        "_id": OID,
        "order_id": "19-11-26-ab12",
        "creator_user": "buyer-user",
        "group": "buyer-1",
        "status": status,
        "offer": {
            "_id": "offer-1", "request_id": "req-1", "user_uid": "seller-uid", "group_id": SELLER,
            "unit_of_measure": "Pieza", "internalComments": "", "publicComments": "",
            "status": "Created", "type": "PartOffer", "price": 100.0,
        },
        "part_request": {
            "_id": "req-1", "creatorGroup": "buyer-1", "creatorUser": "buyer-user", "vehicleId": "veh-1",
            "isActive": True, "partList": [], "status": "Created", "subscribedSellers": [SELLER],
            "part": {"tipoParteDescripcion": "Balata"},
            "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow(),
        },
        "status_history": [],
        "to_be_delivered_time": when,
        "delivery_assignment": assignment,
        "updated_at": datetime.utcnow(),
    }


def _member(uid):
    return {"type": "group_member", "user_id": uid, "assigned_at": datetime.utcnow()}


def _guest(token):
    return {"type": "guest", "guest_token": token, "guest_name": "Beto", "assigned_at": datetime.utcnow()}


@pytest.fixture
def fan():
    names = ["fanout_delivery_assigned", "fanout_delivery_reassigned", "fanout_delivery_time_changed",
             "fanout_delivery_canceled", "fanout_order_status_change", "fanout_order_delayed"]
    patches = [patch.object(notification_fanout, n) for n in names]
    mocks = [p.start() for p in patches]
    yield dict(zip(names, mocks))
    for p in patches:
        p.stop()


def _store(doc):
    """find_by_id returns doc; edit echoes what was saved."""
    return (
        patch.object(OrderService.orderRepository, "find_by_id", return_value=[doc]),
        patch.object(OrderService.orderRepository, "edit", side_effect=lambda _id, data, **kw: {**data, "_id": _id}),
    )


def _assign(doc, uid=None, token=None):
    a, b = _store(doc)
    kind = "guest" if token else "group_member"
    built = DeliveryAssignment(
        type=DeliveryAssignmentType(kind), user_id=uid, guest_token=token,
        guest_name="Beto" if token else None,
    )
    with a, b, patch.object(DeliveryService, "_assert_user_in_group"), \
         patch.object(DeliveryService, "build_delivery_assignment", return_value=built):
        return OrderService.assign_delivery(
            str(OID), kind, "seller-uid", user_id=uid, guest_name="Beto" if token else None, guest_token=token,
        )


def test_assign_sends_assigned(fan):
    _assign(_doc(), uid="rider-1")
    fan["fanout_delivery_assigned"].assert_called_once()
    assert fan["fanout_delivery_assigned"].call_args.kwargs["order"]["delivery_assignment"]["user_id"] == "rider-1"
    fan["fanout_delivery_reassigned"].assert_not_called()


def test_reassign_notifies_previous_rider_and_new_rider(fan):
    previous = _guest("tok-old")
    _assign(_doc(status="WAITING_FOR_COLLECTION", assignment=previous), uid="rider-2")
    fan["fanout_delivery_assigned"].assert_called_once()
    kwargs = fan["fanout_delivery_reassigned"].call_args.kwargs
    assert kwargs["previous_assignment"]["guest_token"] == "tok-old"
    assert kwargs["order"]["delivery_assignment"]["user_id"] == "rider-2"


def test_same_rider_reassigned_sends_no_reassigned(fan):
    _assign(_doc(status="WAITING_FOR_COLLECTION", assignment=_guest("tok-1")), token="tok-1")
    fan["fanout_delivery_reassigned"].assert_not_called()
    fan["fanout_delivery_assigned"].assert_not_called()


def _change_time(doc):
    a, b = _store(doc)
    with a, b:
        return OrderService.change_delivery_time(str(OID), datetime(2026, 11, 19, 21, 0, tzinfo=timezone.utc), False)


def test_time_change_without_assignment_sends_nothing(fan):
    _change_time(_doc(status="DISPATCHED"))
    fan["fanout_delivery_time_changed"].assert_not_called()


@pytest.mark.parametrize("status", ["WAITING_FOR_COLLECTION", "READY_TO_BE_DISPATCHED", "DISPATCHED"])
def test_time_change_with_assignment_sends_time_changed_with_previous_time(fan, status):
    _change_time(_doc(status=status, assignment=_member("rider-1")))
    kwargs = fan["fanout_delivery_time_changed"].call_args.kwargs
    assert kwargs["previous_time"] == datetime(2026, 11, 19, 20, 0)
    assert kwargs["order"]["delivery_assignment"]["user_id"] == "rider-1"


@pytest.mark.parametrize("status", ["RECIEVED", "CANCELED", "CONFIRMED"])
def test_time_change_outside_delivery_statuses_sends_nothing(fan, status):
    _change_time(_doc(status=status, assignment=_member("rider-1")))
    fan["fanout_delivery_time_changed"].assert_not_called()


def _cancel(doc):
    a, b = _store(doc)
    with a, b, patch.object(OrderService, "_assert_order_status_transition"):
        return OrderService.change_order_status(str(OID), "CANCELED", None, None, None)


def test_cancel_notifies_assigned_rider(fan):
    _cancel(_doc(status="DISPATCHED", assignment=_member("rider-1")))
    fan["fanout_delivery_canceled"].assert_called_once()


def test_cancel_without_assignment_sends_nothing(fan):
    _cancel(_doc(status="CONFIRMED"))
    fan["fanout_delivery_canceled"].assert_not_called()


def test_fanout_exception_does_not_break_the_status_change(fan):
    fan["fanout_delivery_canceled"].side_effect = RuntimeError("push down")
    result = _cancel(_doc(status="DISPATCHED", assignment=_member("rider-1")))
    assert result["status"] == "CANCELED"


def test_fanout_exception_does_not_break_assign_or_time_change(fan):
    fan["fanout_delivery_assigned"].side_effect = RuntimeError("down")
    fan["fanout_delivery_time_changed"].side_effect = RuntimeError("down")
    assert _assign(_doc(), uid="rider-1")["delivery_assignment"]["user_id"] == "rider-1"
    assert _change_time(_doc(status="DISPATCHED", assignment=_member("rider-1"))) is not None
