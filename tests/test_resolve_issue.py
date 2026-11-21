"""POST /order/{id}/resolve-issue: who may do what with an open issue, and what each action does."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.services import IssueResolutionService as svc
from app.services import PickupCodeService, notification_fanout
from tests.test_report_failed_delivery import OID, SELLER, _doc

STORE, BUYER, SUPPORT = "store-uid", "buyer-uid", "support-uid"
ISSUE = {"id": "f1", "kind": "delivery", "reason": "no_answer", "resolution": None,
         "at": datetime.utcnow(), "by": {"type": "group_member", "user_id": "rider-1"}, "note": None,
         "photo_urls": [], "client_attempt_id": None}


class Fake:
    """In-memory Orders: the few repository calls the service makes."""

    def __init__(self, doc):
        self.doc = doc
        self.calls = []

    def find_by_id(self, oid):
        return [dict(self.doc)]

    def apply_update(self, oid, set_=None, unset=None):
        self.calls.append(("apply", set_, unset))
        for k, v in (set_ or {}).items():
            node = self.doc
            parts = k.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = v
        for k in unset or []:
            self.doc.pop(k, None)
        return dict(self.doc)

    def resolve_delivery_failure(self, oid, failure_id, resolution):
        for f in self.doc["delivery_failures"]:
            if f["id"] == failure_id and f["resolution"] is None:
                f["resolution"] = resolution
                return dict(self.doc)
        return None

    def mark_return_requested(self, oid, failure_id):
        for f in self.doc["delivery_failures"]:
            if f["id"] == failure_id and f["resolution"] is None:
                f["return_requested"] = True
                return dict(self.doc)
        return None


@pytest.fixture
def env():
    started = []

    def make(status="DISPATCHED", failures=None, issue=True, **extra):
        doc = _doc(status=status, failures=[dict(ISSUE)] if failures is None and issue else (failures or []))
        doc["part_request"]["delivery_contact"] = {"name": "Ana", "phone": "9840000000"}
        doc.update(extra)
        fake = Fake(doc)
        members = {STORE: SELLER, BUYER: "buyer-1"}
        patches = [
            patch.object(svc.orderRepository, "find_by_id", side_effect=fake.find_by_id),
            patch.object(svc.orderRepository, "apply_update", side_effect=fake.apply_update),
            patch.object(svc.orderRepository, "resolve_delivery_failure", side_effect=fake.resolve_delivery_failure),
            patch.object(svc.orderRepository, "mark_return_requested", side_effect=fake.mark_return_requested),
            patch.object(svc, "_user_in_group", side_effect=lambda uid, g: members.get(uid) == g),
            patch.object(notification_fanout, "fanout_issue_resolved"),
            patch.object(notification_fanout, "fanout_delivery_canceled"),
            patch.object(PickupCodeService, "delete_code"),
        ]
        mocks = [p.start() for p in patches]
        fake.resolved_alert, fake.canceled_alert, fake.delete_code = mocks[5], mocks[6], mocks[7]
        fake.patches = patches
        started.append(fake)
        return fake

    yield make
    for f in started:
        for p in f.patches:
            p.stop()


def _go(action, uid, support=False, **kw):
    return svc.resolve_issue(str(OID), action, uid, is_support=support, **kw)


NEW_TIME = (datetime.utcnow() + timedelta(hours=2)).isoformat()
ARGS = {
    "fix_and_retry": {"contact": {"phone": "9841112233", "address": "Calle 10 #5"}},
    "reschedule": {"new_time": NEW_TIME},
    "return_to_store": {},
    "confirm_return": {},
    "cancel": {},
}
ALLOWED = {
    "fix_and_retry": [BUYER, SUPPORT],
    "reschedule": [STORE, SUPPORT],
    "return_to_store": [STORE, SUPPORT],
    "confirm_return": [STORE, SUPPORT],
    "cancel": [STORE, SUPPORT],
}
CASES = [(a, u) for a, users in ALLOWED.items() for u in users]


def _prepare(env, action):
    # confirm_return needs the return to have been requested first
    fake = env()
    if action == "confirm_return":
        fake.doc["delivery_failures"][0]["return_requested"] = True
    return fake


@pytest.mark.parametrize("action,uid", CASES)
def test_each_allowed_role_can_do_each_action(env, action, uid):
    fake = _prepare(env, action)
    result = _go(action, uid, support=(uid == SUPPORT), **ARGS[action])
    assert result["_id"] is not None
    last = fake.doc["delivery_failures"][0]
    if action == "return_to_store":
        assert last["return_requested"] is True and last["resolution"] is None  # stays open
    else:
        assert last["resolution"]["action"] == action


@pytest.mark.parametrize("action,uid", [(a, u) for a in ALLOWED for u in (STORE, BUYER, "stranger")
                                        if u not in ALLOWED[a]])
def test_wrong_role_is_403_for_each_action(env, action, uid):
    fake = _prepare(env, action)
    with pytest.raises(HTTPException) as exc:
        _go(action, uid, **ARGS[action])
    assert exc.value.status_code == 403
    assert fake.doc["delivery_failures"][0]["resolution"] is None


@pytest.mark.parametrize("action", list(ALLOWED))
def test_no_open_issue_is_409(env, action):
    env(issue=False)
    with pytest.raises(HTTPException) as exc:
        _go(action, SUPPORT, support=True, **ARGS[action])
    assert exc.value.status_code == 409


def test_a_resolved_issue_cannot_be_resolved_again(env):
    env(failures=[{**ISSUE, "resolution": {"action": "reschedule"}}])
    with pytest.raises(HTTPException) as exc:
        _go("reschedule", STORE, new_time=NEW_TIME)
    assert exc.value.status_code == 409


def test_fix_and_retry_updates_the_contact_and_does_not_change_the_status(env):
    fake = env(status="DISPATCHED")
    _go("fix_and_retry", BUYER, contact={"phone": "9841112233", "address": "Calle 10 #5"})
    assert fake.doc["status"] == "DISPATCHED"
    assert fake.doc["part_request"]["delivery_contact"]["phone"] == "9841112233"
    assert fake.doc["part_request"]["delivery_address"]["address"] == "Calle 10 #5"
    fake.resolved_alert.assert_called_once()


def test_fix_and_retry_needs_at_least_one_correction(env):
    env()
    with pytest.raises(HTTPException) as exc:
        _go("fix_and_retry", BUYER, contact={})
    assert exc.value.status_code == 400


def test_fix_and_retry_is_for_delivery_issues_only(env):
    env(status="WAITING_FOR_COLLECTION", failures=[{**ISSUE, "kind": "pickup", "reason": "not_ready"}])
    with pytest.raises(HTTPException) as exc:
        _go("fix_and_retry", BUYER, contact={"phone": "9841112233"})
    assert exc.value.status_code == 409


def test_reschedule_needs_a_time(env):
    env()
    with pytest.raises(HTTPException) as exc:
        _go("reschedule", STORE)
    assert exc.value.status_code == 400


def test_reschedule_sets_the_new_time_and_keeps_the_rider(env):
    fake = env()
    _go("reschedule", STORE, new_time=NEW_TIME)
    assert fake.doc["delivery_assignment"]["user_id"] == "rider-1"
    assert fake.doc["to_be_delivered_time"] is not None


def test_reschedule_with_a_new_rider_reassigns_first(env):
    env()
    with patch.object(svc.OrderService, "assign_delivery") as assign:
        _go("reschedule", STORE, new_time=NEW_TIME, new_rider={"assignment_type": "group_member", "user_id": "rider-2"})
    assign.assert_called_once()
    assert assign.call_args.kwargs["user_id"] == "rider-2" and assign.call_args.kwargs["requesting_user_uid"] == STORE


def test_return_to_store_needs_a_picked_up_parcel(env):
    env(status="WAITING_FOR_COLLECTION", failures=[{**ISSUE, "kind": "pickup", "reason": "not_ready"}])
    with pytest.raises(HTTPException) as exc:
        _go("return_to_store", STORE)
    assert exc.value.status_code == 409


def test_confirm_return_needs_the_return_to_be_requested(env):
    env()
    with pytest.raises(HTTPException) as exc:
        _go("confirm_return", STORE)
    assert exc.value.status_code == 409


def test_confirm_return_resets_the_code_and_the_ready_state(env):
    fake = env(picked_up_at=datetime.utcnow(), picked_up_via="code", picked_up_by={"type": "group_member"})
    fake.doc["delivery_failures"][0]["return_requested"] = True
    _go("confirm_return", STORE)
    assert fake.doc["status"] == "READY_TO_BE_DISPATCHED"
    assert "delivery_assignment" not in fake.doc and "picked_up_at" not in fake.doc
    assert "picked_up_via" not in fake.doc and "picked_up_by" not in fake.doc
    assert fake.doc["ready_at"] is not None
    fake.delete_code.assert_called_once_with(str(OID))


def test_cancel_sets_canceled_and_tells_the_rider(env):
    fake = env()
    _go("cancel", STORE)
    assert fake.doc["status"] == "CANCELED"
    fake.canceled_alert.assert_called_once()
    fake.delete_code.assert_called_once_with(str(OID))


def test_cancel_after_pickup_hands_the_alert_the_pickup_so_wording_says_return(env):
    fake = env(picked_up_at=datetime.utcnow())
    _go("cancel", SUPPORT, support=True)
    assert fake.canceled_alert.call_args.kwargs["order"]["picked_up_at"]


def test_the_issue_records_who_resolved_it(env):
    fake = env()
    _go("cancel", STORE, note="El cliente ya no quiere")
    res = fake.doc["delivery_failures"][0]["resolution"]
    assert res["by"] == {"role": "store", "uid": STORE}
    assert res["note"] == "El cliente ya no quiere" and res["action"] == "cancel" and res["at"]


def test_support_is_recorded_as_support_even_when_also_a_member(env):
    fake = env()
    svc_members = {SUPPORT: SELLER}
    with patch.object(svc, "_user_in_group", side_effect=lambda u, g: svc_members.get(u) == g):
        _go("cancel", SUPPORT, support=True)
    assert fake.doc["delivery_failures"][0]["resolution"]["by"]["role"] == "support"


def test_an_unknown_action_is_400(env):
    env()
    with pytest.raises(HTTPException) as exc:
        _go("explode", STORE)
    assert exc.value.status_code == 400


# ── route ────────────────────────────────────────────────────────────────────
import main  # noqa: E402
from tests.asgi_client import AsgiClient  # noqa: E402


def _client(user):
    async def _auth(request):
        request.state.user = user
        request.state.groupSelected = SELLER
        return user

    return patch.object(main, "verify_token", side_effect=_auth)


def test_route_passes_the_caller_and_the_body():
    with _client({"uid": STORE}), patch.object(svc, "resolve_issue", return_value={"ok": 1}) as go:
        res = AsgiClient(main.app).post(
            f"/order/{OID}/resolve-issue",
            json={"action": "reschedule", "new_time": NEW_TIME, "note": "n", "new_rider": {"assignment_type": "group_member", "user_id": "r2"}})
    assert res.status_code == 200
    args, kw = go.call_args
    assert args[:3] == (str(OID), "reschedule", STORE) and kw["is_support"] is False
    assert kw["new_time"] == NEW_TIME and kw["note"] == "n" and kw["new_rider"]["user_id"] == "r2"


def test_route_marks_super_admins_as_support():
    with _client({"uid": SUPPORT, "super_admin": True}), patch.object(svc, "resolve_issue", return_value={}) as go:
        AsgiClient(main.app).post(f"/order/{OID}/resolve-issue", json={"action": "cancel"})
    assert go.call_args.kwargs["is_support"] is True


def test_route_unknown_action_is_422():
    with _client({"uid": STORE}), patch.object(svc, "resolve_issue") as go:
        res = AsgiClient(main.app).post(f"/order/{OID}/resolve-issue", json={"action": "explode"})
    assert res.status_code == 422
    go.assert_not_called()


def test_route_maps_service_errors():
    with _client({"uid": BUYER}), patch.object(svc, "resolve_issue", side_effect=HTTPException(status_code=403, detail="no")):
        res = AsgiClient(main.app).post(f"/order/{OID}/resolve-issue", json={"action": "cancel"})
    assert res.status_code == 403
