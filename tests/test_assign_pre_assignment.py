"""Assigning a rider: allowed while preparing (optional), every rider type goes to
WAITING_FOR_COLLECTION, no "enviado" at assignment, a new code per assignment, and an order marked
ready with a rider already assigned goes straight to waiting for collection."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.schemas.Order import DeliveryAssignment, DeliveryAssignmentType
from app.services import DeliveryService, OrderService, PickupCodeService, notification_fanout
from tests.test_order_delivery_alerts import OID, _doc, _guest, _member, _store


@pytest.fixture
def fan():
    names = ["fanout_delivery_assigned", "fanout_delivery_reassigned", "fanout_delivery_ready",
             "fanout_order_status_change", "fanout_delivery_time_changed", "fanout_delivery_canceled"]
    patches = [patch.object(notification_fanout, n) for n in names]
    mocks = [p.start() for p in patches]
    yield dict(zip(names, mocks))
    for p in patches:
        p.stop()


@pytest.fixture
def codes():
    with patch.object(PickupCodeService, "reset_code", return_value="4729") as reset:
        yield reset


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


def _mark(doc, new_status):
    a, b = _store(doc)
    with a, b, patch.object(OrderService, "_assert_order_status_transition"):
        return OrderService.change_order_status(str(OID), new_status, None, None, None)


def test_pre_assign_in_confirmed_keeps_confirmed_and_creates_a_code(fan, codes):
    result = _assign(_doc(status="CONFIRMED"), uid="rider-1")
    assert result["status"] == "CONFIRMED"
    assert result["delivery_assignment"]["user_id"] == "rider-1"
    codes.assert_called_once_with(str(OID))
    assert fan["fanout_delivery_assigned"].call_args.kwargs["preparing"] is True


def test_assign_in_ready_sends_account_riders_to_waiting_for_collection(fan, codes):
    result = _assign(_doc(status="READY_TO_BE_DISPATCHED"), uid="rider-1")
    assert result["status"] == "WAITING_FOR_COLLECTION"
    assert fan["fanout_delivery_assigned"].call_args.kwargs.get("preparing") is False


def test_assign_in_ready_sends_guests_to_waiting_for_collection(fan, codes):
    assert _assign(_doc(status="READY_TO_BE_DISPATCHED"), token="tok-1")["status"] == "WAITING_FOR_COLLECTION"


def test_no_order_sent_notification_on_assignment(fan, codes):
    _assign(_doc(status="READY_TO_BE_DISPATCHED"), uid="rider-1")
    _assign(_doc(status="CONFIRMED"), token="tok-1")
    fan["fanout_order_status_change"].assert_not_called()


def test_reassign_replaces_the_code_and_alerts_the_previous_rider(fan, codes):
    _assign(_doc(status="WAITING_FOR_COLLECTION", assignment=_member("rider-1")), uid="rider-2")
    codes.assert_called_once_with(str(OID))
    assert fan["fanout_delivery_reassigned"].call_args.kwargs["previous_assignment"]["user_id"] == "rider-1"


def test_reassign_while_waiting_does_not_repeat_the_status_history(fan, codes):
    result = _assign(_doc(status="WAITING_FOR_COLLECTION", assignment=_member("rider-1")), uid="rider-2")
    assert result["status"] == "WAITING_FOR_COLLECTION"
    assert len(result["status_history"]) == 0


@pytest.mark.parametrize("status", ["WAITING_FOR_CONFIRMATION", "DISPATCHED", "RECIEVED", "CANCELED"])
def test_assign_still_refuses_other_statuses(fan, codes, status):
    with pytest.raises(HTTPException) as exc:
        _assign(_doc(status=status), uid="rider-1")
    assert exc.value.status_code == 400
    codes.assert_not_called()


def test_pre_assigned_order_marked_ready_goes_to_waiting_for_collection_and_alerts_the_rider(fan):
    result = _mark(_doc(status="CONFIRMED", assignment=_member("rider-1")), "READY_TO_BE_DISPATCHED")
    assert result["status"] == "WAITING_FOR_COLLECTION"
    assert result["ready_at"] is not None
    fan["fanout_delivery_ready"].assert_called_once()
    assert fan["fanout_delivery_ready"].call_args.kwargs["order"]["delivery_assignment"]["user_id"] == "rider-1"


def test_order_marked_ready_without_a_rider_only_sets_ready_at(fan):
    result = _mark(_doc(status="CONFIRMED"), "READY_TO_BE_DISPATCHED")
    assert result["status"] == "READY_TO_BE_DISPATCHED"
    assert result["ready_at"] is not None
    fan["fanout_delivery_ready"].assert_not_called()


def test_a_guest_pre_assigned_order_marked_ready_alerts_the_guest_feed(fan):
    result = _mark(_doc(status="CONFIRMED", assignment=_guest("tok-1")), "READY_TO_BE_DISPATCHED")
    assert result["status"] == "WAITING_FOR_COLLECTION"
    fan["fanout_delivery_ready"].assert_called_once()
