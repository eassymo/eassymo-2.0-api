"""cancel_by_seller: the selling store backs out of an order that is still at the store."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.services import OrderCancellationService as svc
from app.services import NotificationService, PickupCodeService, notification_fanout
from tests.test_report_failed_delivery import OID, SELLER, _doc

STORE, STRANGER = "store-uid", "stranger-uid"


class Fake:
    def __init__(self, doc):
        self.doc = doc
        self.calls = []
        self.race_lost = False

    def find_by_id(self, oid):
        return [dict(self.doc)]

    def cancel_if_status(self, oid, allowed, set_):
        self.calls.append(("cancel", allowed, set_))
        if self.race_lost or self.doc["status"] not in allowed:
            return None
        self.doc.update(set_)
        return dict(self.doc)


@pytest.fixture
def env():
    started = []

    def make(status="WAITING_FOR_CONFIRMATION", **extra):
        doc = _doc(status=status, assignment=extra.pop("assignment", None))
        doc["delivery_assignment"] = extra.pop("delivery_assignment", None)
        doc["status_history"] = []
        doc.update(extra)
        fake = Fake(doc)
        offers = MagicMock()
        offers.find.return_value = [{"_id": "x1"}, {"_id": "x2"}]
        rsg = MagicMock()
        rsg.find_by_group_and_request_id.return_value = None
        pr = MagicMock()
        patches = [
            patch.object(svc.orderRepository, "find_by_id", side_effect=fake.find_by_id),
            patch.object(svc.orderRepository, "cancel_if_status", side_effect=fake.cancel_if_status),
            patch.object(svc, "_user_in_group", side_effect=lambda uid, g: uid == STORE and g == SELLER),
            patch.object(svc, "offerRepository", offers),
            patch.object(svc, "requestStatusByGroupRepository", rsg),
            patch.object(svc, "partRequestRepository", pr),
            patch.object(svc.groupRepository, "find_by_id", return_value={"name": "AUTOPARTES ALEX"}),
            patch.object(PickupCodeService, "delete_code"),
            patch.object(notification_fanout, "fanout_order_canceled"),
            patch.object(notification_fanout, "fanout_delivery_canceled"),
            patch.object(NotificationService, "resolve_decisions"),
        ]
        mocks = [p.start() for p in patches]
        fake.offers, fake.rsg, fake.pr = offers, rsg, pr
        fake.delete_code, fake.fanout, fake.rider_alert, fake.resolve = mocks[7], mocks[8], mocks[9], mocks[10]
        fake.patches = patches
        started.append(fake)
        return fake

    yield make
    for f in started:
        for p in f.patches:
            p.stop()


def _go(uid=STORE, reason="sold", note="Se vendió en mostrador"):
    return svc.cancel_by_seller(str(OID), uid, reason, note)


@pytest.mark.parametrize("status", sorted(s.value for s in svc.SELLER_CANCELABLE))
def test_each_cancelable_status_cancels(env, status):
    fake = env(status)
    result = _go()
    assert result["status"] == "CANCELED"
    assert fake.doc["status_history"][-1]["status"] == "CANCELED"
    c = fake.doc["cancellation"]
    assert (c["by"], c["group_id"], c["user_id"], c["reason"], c["note"]) == ("seller", SELLER, STORE, "sold", "Se vendió en mostrador")
    assert isinstance(c["at"], datetime)


@pytest.mark.parametrize("status,detail", [
    ("DISPATCHED", "La pieza ya salió de la tienda."),
    ("RECIEVED", "La pieza ya salió de la tienda."),
    ("CANCELED", "Esta orden ya fue cancelada."),
])
def test_not_cancelable_status_is_409(env, status, detail):
    fake = env(status)
    with pytest.raises(HTTPException) as exc:
        _go()
    assert exc.value.status_code == 409 and exc.value.detail == detail
    assert not fake.fanout.called


def test_mostrador_is_409(env):
    env(origin="mostrador")
    with pytest.raises(HTTPException) as exc:
        _go()
    assert exc.value.status_code == 409 and exc.value.detail == "Las órdenes de mostrador se cancelan desde el mostrador."


def test_not_seller_is_403(env):
    env()
    with pytest.raises(HTTPException) as exc:
        _go(uid=STRANGER)
    assert exc.value.status_code == 403 and exc.value.detail == "Solo la tienda que vende puede cancelar esta orden."


@pytest.mark.parametrize("reason,note", [("x", None), ("sold", "a" * 201)])
def test_invalid_input_is_422(env, reason, note):
    env()
    with pytest.raises(HTTPException) as exc:
        _go(reason=reason, note=note)
    assert exc.value.status_code == 422


def test_note_is_trimmed_and_blank_becomes_none(env):
    fake = env()
    _go(note="   ")
    assert fake.doc["cancellation"]["note"] is None


def test_race_loser_gets_409_and_nothing_else_changes(env):
    fake = env("CONFIRMED")
    fake.race_lost = True
    with pytest.raises(HTTPException) as exc:
        _go()
    assert exc.value.status_code == 409 and exc.value.detail == "La pieza ya salió de la tienda."
    fake.offers.edit_offer.assert_not_called()
    fake.pr.edit_part_request.assert_not_called()
    fake.rsg.insert.assert_not_called()
    fake.fanout.assert_not_called()
    fake.resolve.assert_not_called()


def test_side_effects(env):
    fake = env()
    _go()
    fake.offers.edit_offer.assert_called_once_with("offer-1", {"status": "No_Inventory"})
    saved = fake.rsg.insert.call_args.args[0]
    assert (saved.group_id, saved.request_id, saved.status.value) == (SELLER, "req-1", "No_Inventory")
    request_id, data = fake.pr.edit_part_request.call_args.args
    assert request_id == "req-1" and data["status"] == "Created" and data["isActive"] is True
    last = data["last_cancellation"]
    assert last["store_name"] == "Autopartes Alex" and last["store_group_id"] == SELLER
    assert last["order_id"] == str(OID) and last["reason"] == "sold"
    fake.delete_code.assert_called_once_with(str(OID))
    assert fake.fanout.call_count == 1 and fake.fanout.call_args.kwargs["remaining_offers"] == 2
    fake.resolve.assert_called_once_with(f"order:{OID}:confirm")


def test_existing_request_status_is_updated_not_duplicated(env):
    fake = env()
    existing = MagicMock(id="rs1", status=None)
    fake.rsg.find_by_group_and_request_id.return_value = existing
    _go()
    fake.rsg.insert.assert_not_called()
    fake.rsg.update.assert_called_once()


def test_assigned_rider_gets_the_canceled_alert_with_assignment(env):
    assignment = {"type": "group_member", "user_id": "rider-1", "assigned_at": datetime.utcnow()}
    fake = env("WAITING_FOR_COLLECTION", delivery_assignment=assignment)
    _go()
    alerted = fake.rider_alert.call_args.kwargs["order"]
    assert alerted["delivery_assignment"]["user_id"] == "rider-1"
    fake.delete_code.assert_called_once()
