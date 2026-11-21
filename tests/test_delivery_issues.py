"""Failed pickup + the issue model: kinds, reasons, status gate, open issue, alerts, replay."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.schemas.DeliveryFailure import open_issue
from app.schemas.GuestDeliveryProfile import GuestDeliveryProfileStatus
from app.services import DeliveryService as svc
from app.services import notification_fanout
from tests.test_report_failed_delivery import OID, Store, _doc, GUEST, TOKEN


@pytest.fixture
def env():
    made = []

    def factory(doc):
        store = Store(doc)
        patches = [
            patch.object(svc.orderRepository, "find_one", side_effect=store.find_one),
            patch.object(svc.orderRepository, "push_delivery_failure", side_effect=store.push_delivery_failure),
            patch.object(svc.orderRepository, "edit", side_effect=AssertionError("status must not be rewritten")),
            patch.object(notification_fanout, "fanout_delivery_failed"),
            patch.object(svc, "_assert_has_delivery_role"),
            patch.object(svc.guestProfileRepository, "find_by_token",
                         return_value={"token": TOKEN, "name": "Beto", "status": GuestDeliveryProfileStatus.ACTIVE}),
        ]
        mocks = [p.start() for p in patches]
        store.notify = mocks[3]
        store.patches = patches
        made.append(store)
        return store

    yield factory
    for s in made:
        for p in s.patches:
            p.stop()


def _report(**kw):
    args = dict(order_id=str(OID), reason="no_answer", note=None, photo_urls=[], client_attempt_id=None,
                user_uid="rider-1", guest_token=None)
    args.update(kw)
    return svc.report_failed(**args)


@pytest.mark.parametrize("reason", ["store_closed", "not_ready", "wrong_item", "damaged", "other"])
def test_pickup_failure_reasons_are_accepted_for_kind_pickup(env, reason):
    store = env(_doc(status="WAITING_FOR_COLLECTION"))
    assert _report(kind="pickup", reason=reason)["recorded"] is True
    assert store.writes[0]["kind"] == "pickup" and store.writes[0]["reason"] == reason


@pytest.mark.parametrize("kind,reason", [("delivery", "store_closed"), ("pickup", "no_answer"),
                                         ("delivery", "damaged")])
def test_a_reason_of_the_other_kind_is_rejected(env, kind, reason):
    store = env(_doc(status="WAITING_FOR_COLLECTION"))
    with pytest.raises(HTTPException) as exc:
        _report(kind=kind, reason=reason)
    assert exc.value.status_code == 400 and store.writes == []


@pytest.mark.parametrize("status", ["CONFIRMED", "READY_TO_BE_DISPATCHED", "DISPATCHED", "RECIEVED"])
def test_a_pickup_failure_is_refused_outside_waiting_for_collection(env, status):
    store = env(_doc(status=status))
    with pytest.raises(HTTPException) as exc:
        _report(kind="pickup", reason="not_ready")
    assert exc.value.status_code == 400 and store.writes == []


def test_delivery_failure_still_works_as_before(env):
    store = env(_doc(status="DISPATCHED"))
    assert _report() == {"recorded": True, "failures": 1}
    f = store.writes[0]
    assert f["kind"] == "delivery" and f["resolution"] is None and f["id"]


def test_opening_an_issue_alerts_the_store(env):
    store = env(_doc(status="WAITING_FOR_COLLECTION", assignment=GUEST))
    with patch.object(notification_fanout, "fanout_delivery_issue") as issue:
        _report(user_uid=None, guest_token=TOKEN, kind="pickup", reason="store_closed")
    issue.assert_called_once()
    assert issue.call_args.kwargs["failure"]["kind"] == "pickup"


def test_opening_a_delivery_issue_alerts_the_buyer_too(env):
    env(_doc(status="DISPATCHED"))
    with patch.object(notification_fanout, "fanout_delivery_issue") as issue:
        _report()
    assert issue.call_args.kwargs["failure"]["kind"] == "delivery"


def test_open_issue_is_derived_from_the_last_unresolved_failure():
    assert open_issue(None) is None and open_issue([]) is None
    resolved = {"id": "a", "resolution": {"action": "reschedule"}}
    unresolved = {"id": "b", "resolution": None}
    assert open_issue([resolved]) is None
    assert open_issue([resolved, unresolved]) is unresolved
    assert open_issue([unresolved, resolved]) is None
    assert open_issue([{"reason": "no_answer"}]) is None  # recorded before issues existed: no "resolution" key, never open


def test_replay_with_the_same_client_attempt_id_records_once(env):
    store = env(_doc(status="DISPATCHED"))
    _report(client_attempt_id="c1")
    _report(client_attempt_id="c1")
    assert len(store.writes) == 1


def test_order_payload_keeps_the_issue_fields_the_client_needs():
    from app.schemas.Order import Order

    doc = _doc(status="DISPATCHED", failures=[{
        "id": "f1", "kind": "delivery", "reason": "no_answer", "resolution": None, "return_requested": True,
        "note": None, "photo_urls": [], "at": __import__("datetime").datetime.utcnow(), "by": {}, "client_attempt_id": None,
    }])
    failure = Order(**doc).toJson()["delivery_failures"][0]
    assert failure["id"] == "f1" and failure["kind"] == "delivery"
    assert failure["resolution"] is None and failure["return_requested"] is True
