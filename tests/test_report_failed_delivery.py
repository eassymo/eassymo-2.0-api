"""POST /delivery/report-failed: the assigned rider (account or guest) records a failed
attempt; status never changes; replays with the same client_attempt_id record once;
the selling group is told."""
from datetime import datetime
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

import main
from app.schemas.GuestDeliveryProfile import GuestDeliveryProfileStatus
from app.schemas.Order import Order
from app.services import DeliveryService as svc
from app.services import notification_fanout
from tests.asgi_client import AsgiClient

OID = ObjectId()
TOKEN = "tok-guest-a"
SELLER = "seller-group"


def _doc(status="DISPATCHED", assignment=None, failures=None):
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
        "delivery_assignment": assignment or {"type": "group_member", "user_id": "rider-1",
                                              "assigned_at": datetime.utcnow()},
        "delivery_failures": failures,
        "updated_at": datetime.utcnow(),
    }


GUEST = {"type": "guest", "guest_token": TOKEN, "guest_name": "Beto", "assigned_at": datetime.utcnow()}


class Store:
    """Fake Orders storage: push only when client_attempt_id is new (like the Mongo filter)."""

    def __init__(self, doc):
        self.doc = doc
        self.writes = []

    def find_one(self, filters):
        return dict(self.doc) if filters.get("_id") == self.doc["_id"] else None

    def push_delivery_failure(self, oid, failure, client_attempt_id):
        existing = self.doc.get("delivery_failures") or []
        if client_attempt_id and any(f.get("client_attempt_id") == client_attempt_id for f in existing):
            return None
        self.writes.append(failure)
        self.doc = {**self.doc, "delivery_failures": [*existing, failure]}
        return dict(self.doc)


@pytest.fixture
def env():
    def make(doc):
        store = Store(doc)
        patches = [
            patch.object(svc.orderRepository, "find_one", side_effect=store.find_one),
            patch.object(svc.orderRepository, "push_delivery_failure", side_effect=store.push_delivery_failure),
            patch.object(svc.orderRepository, "edit", side_effect=AssertionError("status must not be rewritten")),
            patch.object(notification_fanout, "fanout_delivery_failed"),
            patch.object(svc.guestProfileRepository, "find_by_token",
                         return_value={"token": TOKEN, "name": "Beto", "status": GuestDeliveryProfileStatus.ACTIVE}),
            patch.object(svc, "_assert_has_delivery_role"),
        ]
        mocks = [p.start() for p in patches]
        store.notify = mocks[3]
        store.patches = patches
        return store

    made = []

    def factory(doc):
        s = make(doc)
        made.append(s)
        return s

    yield factory
    for s in made:
        for p in s.patches:
            p.stop()


def _report(**kw):
    args = dict(order_id=str(OID), reason="no_answer", note=None, photo_urls=[], client_attempt_id=None,
                user_uid="rider-1", guest_token=None)
    args.update(kw)
    return svc.report_failed(**args)


def test_assigned_account_rider_records_a_failure(env):
    store = env(_doc())
    assert _report(note="toqué 3 veces", photo_urls=["https://x/p.jpg"]) == {"recorded": True, "failures": 1}
    f = store.writes[0]
    assert f["reason"] == "no_answer" and f["note"] == "toqué 3 veces" and f["photo_urls"] == ["https://x/p.jpg"]
    assert f["by"] == {"type": "group_member", "user_id": "rider-1"}
    assert isinstance(f["at"], datetime)


def test_assigned_guest_records_a_failure(env):
    store = env(_doc(status="WAITING_FOR_COLLECTION", assignment=GUEST))
    assert _report(user_uid=None, guest_token=TOKEN, reason="wrong_address")["failures"] == 1
    assert store.writes[0]["by"] == {"type": "guest", "name": "Beto"}
    assert TOKEN not in str(store.writes[0])


@pytest.mark.parametrize("kw", [
    {"user_uid": "other-rider"},
    {"user_uid": None, "guest_token": TOKEN},  # guest reporting an account rider's order
])
def test_another_rider_is_403(env, kw):
    store = env(_doc())
    with pytest.raises(HTTPException) as exc:
        _report(**kw)
    assert exc.value.status_code == 403
    assert store.writes == []


def test_other_guest_token_is_403(env):
    env(_doc(assignment={**GUEST, "guest_token": "tok-guest-b"}))
    with pytest.raises(HTTPException) as exc:
        _report(user_uid=None, guest_token=TOKEN)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("status", ["RECIEVED", "CANCELED", "CONFIRMED", "WAITING_FOR_CONFIRMATION"])
def test_order_not_in_an_active_delivery_status_is_400(env, status):
    env(_doc(status=status))
    with pytest.raises(HTTPException) as exc:
        _report()
    assert exc.value.status_code == 400


def test_unknown_order_is_404(env):
    env(_doc())
    with pytest.raises(HTTPException) as exc:
        _report(order_id=str(ObjectId()))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _report(order_id="not-an-id")
    assert exc.value.status_code == 404


def test_status_is_unchanged(env):
    store = env(_doc(status="DISPATCHED"))
    _report()
    assert store.doc["status"] == "DISPATCHED"  # edit() would raise if called


def test_same_client_attempt_id_twice_records_once(env):
    store = env(_doc())
    first = _report(client_attempt_id="att-1")
    second = _report(client_attempt_id="att-1")
    assert first == second == {"recorded": True, "failures": 1}
    assert len(store.writes) == 1
    assert store.notify.call_count == 1


def test_different_attempts_record_twice(env):
    store = env(_doc())
    _report(client_attempt_id="att-1")
    assert _report(client_attempt_id="att-2")["failures"] == 2
    assert len(store.writes) == 2


def test_seller_group_is_notified(env):
    store = env(_doc())
    _report(reason="other", note="portón cerrado")
    kwargs = store.notify.call_args.kwargs
    assert kwargs["order"]["offer"]["group_id"] == SELLER
    assert kwargs["failure"]["reason"] == "other" and kwargs["failure"]["note"] == "portón cerrado"


def test_notify_failure_does_not_lose_the_record(env):
    store = env(_doc())
    store.notify.side_effect = RuntimeError("down")
    assert _report()["recorded"] is True


def test_delivery_failures_are_included_in_delivery_orders():
    failure = {"reason": "no_answer", "note": None, "photo_urls": [], "at": datetime(2026, 11, 19, 20),
               "by": {"type": "group_member", "user_id": "rider-1"}, "client_attempt_id": "att-1"}
    with patch.object(svc.orderRepository, "find", return_value=[_doc(failures=[failure])]):
        orders = svc._fetch_orders_for_delivery({})
    assert orders[0]["delivery_failures"][0]["reason"] == "no_answer"
    assert orders[0]["delivery_failures"][0]["at"] == "2026-11-19T20:00:00.000Z"


def test_order_without_failures_still_validates():
    assert Order(**_doc()).toJson()["delivery_failures"] is None


# ── route ────────────────────────────────────────────────────────────────────

async def _account(request):
    request.state.user = {"uid": "rider-1"}
    request.state.groupSelected = SELLER
    return request.state.user


@pytest.fixture
def client():
    with patch.object(main, "verify_token", side_effect=_account):
        yield AsgiClient(main.app)


def test_invalid_reason_is_422(client):
    with patch.object(svc, "report_failed") as report:
        res = client.post("/delivery/report-failed", json={"order_id": str(OID), "reason": "flat_tire"})
    assert res.status_code == 422
    report.assert_not_called()


def test_photo_urls_capped_at_5(client):
    with patch.object(svc, "report_failed") as report:
        res = client.post("/delivery/report-failed",
                          json={"order_id": str(OID), "reason": "other", "photo_urls": [f"u{i}" for i in range(6)]})
    assert res.status_code == 422
    report.assert_not_called()


def test_route_passes_account_caller(client):
    with patch.object(svc, "report_failed", return_value={"recorded": True, "failures": 1}) as report:
        res = client.post("/delivery/report-failed",
                          json={"order_id": str(OID), "reason": "no_answer", "client_attempt_id": "a1",
                                "photo_urls": ["u1"]})
    assert res.status_code == 200
    assert res.json()["body"] == {"recorded": True, "failures": 1}
    kw = report.call_args.kwargs
    assert kw["user_uid"] == "rider-1" and kw["guest_token"] is None
    assert kw["reason"] == "no_answer" and kw["client_attempt_id"] == "a1" and kw["photo_urls"] == ["u1"]


def test_route_guest_skips_firebase_and_uses_header_token(client):
    with patch.object(svc, "report_failed", return_value={"recorded": True, "failures": 1}) as report, \
         patch.object(main, "verify_token", side_effect=AssertionError("guest must not need Firebase")):
        res = client.post("/delivery/report-failed", headers={"X-Guest-Token": TOKEN},
                          json={"order_id": str(OID), "reason": "nobody_to_receive"})
    assert res.status_code == 200
    assert report.call_args.kwargs["guest_token"] == TOKEN
    assert report.call_args.kwargs["user_uid"] is None


# ── review fixes ─────────────────────────────────────────────────────────────

def test_whole_order_save_never_overwrites_delivery_failures():
    """Only push_delivery_failure writes the list; a stale Order.toJson() $set must not erase it."""
    from unittest.mock import MagicMock
    from app.repositories import OrderRepository

    coll = MagicMock()
    with patch.object(OrderRepository.database, "db", {"Orders": coll}):
        OrderRepository.edit(OID, {"status": "DISPATCHED", "delivery_failures": []})
    update = coll.find_one_and_update.call_args.args[1]
    assert update == {"$set": {"status": "DISPATCHED"}}


def _recorded(attempt="att-1", by=None):
    return {"reason": "no_answer", "note": None, "photo_urls": [], "at": datetime(2026, 11, 19, 20),
            "by": by or {"type": "group_member", "user_id": "rider-1"}, "client_attempt_id": attempt}


@pytest.mark.parametrize("later", [
    {"status": "CANCELED"},
    {"delivery_assignment": {"type": "group_member", "user_id": "rider-2", "assigned_at": datetime.utcnow()}},
])
def test_replay_after_the_order_moved_on_still_answers_recorded(env, later):
    store = env({**_doc(failures=[_recorded()]), **later})
    assert _report(client_attempt_id="att-1") == {"recorded": True, "failures": 1}
    assert store.writes == []
    store.notify.assert_not_called()


def test_replay_by_a_guest_after_reassignment_answers_recorded(env):
    store = env(_doc(failures=[_recorded(by={"type": "guest", "name": "Beto"})]))
    assert _report(user_uid=None, guest_token=TOKEN, client_attempt_id="att-1")["failures"] == 1
    assert store.writes == []


def test_someone_else_cannot_replay_an_account_riders_attempt(env):
    env(_doc(failures=[_recorded()]))
    with pytest.raises(HTTPException) as exc:
        _report(user_uid="other-rider", client_attempt_id="att-1")
    assert exc.value.status_code == 403
