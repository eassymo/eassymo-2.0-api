"""Delivery alerts for riders (account or guest) and the 'failed' alert for the seller.

Runs the real fan-out -> NotificationService -> push pipeline; only storage, the realtime bus,
push delivery and group/user lookups are faked.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services import NotificationService, notification_fanout as fanout

SELLER = "seller-group"
BUYER = "buyer-group"
ORDER_ID = "6560f0aa0000000000000001"
TOKEN = "guest-token-1"


def _order(assignment=None, **extra):
    order = {
        "_id": ORDER_ID,
        "order_id": "19-11-26-ab12",
        "status": "DISPATCHED",
        "offer": {"group_id": SELLER},
        "offer_group": {"_id": SELLER, "name": "Refacciones Lupita"},
        "request_group": {"_id": BUYER, "name": "Taller Pepe"},
        "part_request": {
            "creatorGroup": BUYER,
            "part": {"tipoParteDescripcion": "Balata delantera"},
            "delivery_address": {"address": "Av. Juárez 10"},
        },
        "to_be_delivered_time": "2026-11-19T20:49:00.000Z",
        "delivery_assignment": assignment,
    }
    order.update(extra)
    return order


ACCOUNT = {"type": "group_member", "user_id": "rider-uid"}
GUEST = {"type": "guest", "guest_token": TOKEN, "guest_name": "Beto"}


@pytest.fixture
def sent():
    """Captures stored notifications and pushes."""
    stored, pushes = [], []

    def insert_many(docs):
        out = [{**d, "_id": f"n{i}"} for i, d in enumerate(docs)]
        stored.extend(out)
        return out

    with patch.object(NotificationService.notificationRepository, "insert_many", side_effect=insert_many), \
         patch.object(NotificationService.realtime_bus, "publish_inbox_event"), \
         patch.object(NotificationService.push_service, "send_push_from_notification",
                      side_effect=lambda doc: pushes.append(doc)), \
         patch.object(fanout, "_user_name", return_value="Carla"):
        yield stored, pushes


def test_account_rider_gets_an_owned_notification_and_a_push(sent):
    stored, pushes = sent
    fanout.fanout_delivery_assigned(order=_order(ACCOUNT))
    assert len(stored) == 1
    n = stored[0]
    assert n["type"] == "DELIVERY_ASSIGNED"
    assert n["owner"] == "rider-uid"
    assert n["ownerGroup"] == SELLER
    assert "guest_token" not in n
    assert n["navigateToUrl"] == f"/deliveries/{ORDER_ID}"
    assert n["metaData"]["orderId"] == ORDER_ID
    assert [p["owner"] for p in pushes] == ["rider-uid"]


def test_guest_rider_gets_guest_token_and_no_push(sent):
    stored, pushes = sent
    fanout.fanout_delivery_assigned(order=_order(GUEST))
    assert len(stored) == 1
    n = stored[0]
    assert n["guest_token"] == TOKEN
    assert n["owner"] == ""
    assert n["navigateToUrl"] == f"/delivery/guest/{ORDER_ID}?token={TOKEN}"
    assert pushes == []


def test_message_texts_match_the_copy(sent):
    stored, _ = sent
    fanout.fanout_delivery_assigned(order=_order(ACCOUNT))
    fanout.fanout_delivery_reassigned(
        order=_order({"type": "guest", "guest_token": "t2", "guest_name": "Beto"}),
        previous_assignment=ACCOUNT,
    )
    fanout.fanout_delivery_canceled(order=_order(GUEST))
    assert [n["message"] for n in stored] == [
        "Te asignaron una entrega. Recoger en Refacciones Lupita, entregar a Taller Pepe",
        "Te reasignaron. La orden de Av. Juárez 10 pasó a Beto. Ya no es tuya.",
        "Cancelaron la orden. Balata delantera, Refacciones Lupita. No la recojas.",
    ]
    assert stored[0]["metaData"]["title"] == "Te asignaron una entrega"
    assert stored[0]["metaData"]["body"] == "Recoger en Refacciones Lupita, entregar a Taller Pepe"
    # the reassigned alert goes to the previous rider, not the new one
    assert stored[1]["owner"] == "rider-uid"
    assert stored[1]["type"] == "DELIVERY_REASSIGNED"


def test_reassigned_names_an_account_rider_by_user_name(sent):
    stored, _ = sent
    fanout.fanout_delivery_reassigned(
        order=_order({"type": "group_member", "user_id": "new-uid"}), previous_assignment=GUEST
    )
    assert stored[0]["message"] == "Te reasignaron. La orden de Av. Juárez 10 pasó a Carla. Ya no es tuya."
    assert stored[0]["guest_token"] == TOKEN


def test_time_shown_in_mexico_city(sent):
    stored, _ = sent
    fanout.fanout_delivery_time_changed(
        order=_order(ACCOUNT),
        previous_time=datetime(2026, 11, 19, 19, 30, tzinfo=timezone.utc),
    )
    # 20:49Z -> 14:49 and 19:30Z -> 13:30 in America/Mexico_City (UTC-6)
    assert stored[0]["message"] == "Cambió la hora de entrega. Taller Pepe: ahora a las 14:49 (antes 13:30)"
    assert stored[0]["type"] == "DELIVERY_TIME_CHANGED"


def test_time_changed_without_previous_time_omits_antes(sent):
    stored, _ = sent
    fanout.fanout_delivery_time_changed(order=_order(GUEST))
    assert stored[0]["message"] == "Cambió la hora de entrega. Taller Pepe: ahora a las 14:49"


@pytest.mark.parametrize("call", [
    lambda o: fanout.fanout_delivery_assigned(order=o),
    lambda o: fanout.fanout_delivery_time_changed(order=o),
    lambda o: fanout.fanout_delivery_canceled(order=o),
    lambda o: fanout.fanout_delivery_reassigned(order=o, previous_assignment=None),
])
def test_order_with_no_assignment_sends_nothing(sent, call):
    stored, pushes = sent
    call(_order(None))
    assert stored == [] and pushes == []


def test_failed_goes_to_the_selling_group_not_the_rider(sent):
    stored, pushes = sent
    groups = [{"_id": SELLER, "users": ["owner-uid", "rider-uid", "clerk-uid"]}]
    with patch.object(fanout, "_users_by_group_ids", return_value=groups) as by_group:
        fanout.fanout_delivery_failed(
            order=_order(ACCOUNT),
            failure={"reason": "no_answer", "note": None, "by": {"type": "group_member", "user_id": "rider-uid"}},
        )
    by_group.assert_called_once_with([SELLER])
    assert sorted(n["owner"] for n in stored) == ["clerk-uid", "owner-uid"]
    assert all(n["type"] == "DELIVERY_FAILED" and n["ownerGroup"] == SELLER for n in stored)
    assert stored[0]["message"] == "No se pudo entregar. Balata delantera: no contestan."
    assert stored[0]["visibleRoles"] == ["212", "213"]
    assert all("guest_token" not in n for n in stored)


@pytest.mark.parametrize("reason,text", [
    ("no_answer", "no contestan"),
    ("wrong_address", "la dirección no es correcta"),
    ("nobody_to_receive", "no había quien recibiera"),
    ("other", "otro motivo"),
])
def test_failed_reason_texts(sent, reason, text):
    stored, _ = sent
    with patch.object(fanout, "_users_by_group_ids", return_value=[{"_id": SELLER, "users": ["owner-uid"]}]):
        fanout.fanout_delivery_failed(order=_order(GUEST), failure={"reason": reason})
    assert stored[0]["message"] == f"No se pudo entregar. Balata delantera: {text}."


def test_failed_other_reason_shows_the_note(sent):
    stored, _ = sent
    with patch.object(fanout, "_users_by_group_ids", return_value=[{"_id": SELLER, "users": ["owner-uid"]}]):
        fanout.fanout_delivery_failed(order=_order(GUEST), failure={"reason": "other", "note": "portón cerrado"})
    assert stored[0]["message"] == "No se pudo entregar. Balata delantera: otro motivo (portón cerrado)."
