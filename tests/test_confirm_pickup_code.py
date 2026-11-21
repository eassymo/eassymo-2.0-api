"""The rider (account or guest) confirms pickup by typing the store's code; without a code a photo
is the escape hatch (flagged to the store). Orders created before codes existed keep the old tap."""
from datetime import datetime
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.services import DeliveryService as svc
from app.services import PickupCodeService, notification_fanout
from tests.test_pickup_code import FakeRepo

OID = ObjectId()
TOKEN = "tok-guest-a"
SELLER = "seller-group"
GUEST = {"type": "guest", "guest_token": TOKEN, "guest_name": "Beto", "assigned_at": datetime.utcnow()}
MEMBER = {"type": "group_member", "user_id": "rider-1", "assigned_at": datetime.utcnow()}


def _doc(status="WAITING_FOR_COLLECTION", assignment=GUEST):
    return {
        "_id": OID, "order_id": "21-11-26-ab12", "creator_user": "buyer-user", "group": "buyer-1", "status": status,
        "offer": {"_id": "offer-1", "request_id": "req-1", "user_uid": "seller-uid", "group_id": SELLER,
                  "unit_of_measure": "Pieza", "internalComments": "", "publicComments": "",
                  "status": "Created", "type": "PartOffer", "price": 100.0},
        "part_request": {"_id": "req-1", "creatorGroup": "buyer-1", "creatorUser": "buyer-user", "vehicleId": "veh-1",
                         "isActive": True, "partList": [], "status": "Created", "subscribedSellers": [SELLER],
                         "part": {"tipoParteDescripcion": "Balata"},
                         "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow()},
        "status_history": [], "delivery_assignment": assignment, "updated_at": datetime.utcnow(),
    }


@pytest.fixture
def env():
    repo = FakeRepo()
    saved = {}
    fans = {n: patch.object(notification_fanout, n) for n in ["fanout_order_status_change", "fanout_delivery_handed_off"]}
    mocks = {n: p.start() for n, p in fans.items()}
    store = {"doc": _doc()}

    def edit(_id, data):
        saved.clear()
        saved.update(data)
        store["doc"] = {**data, "_id": _id}
        return store["doc"]

    with patch.object(PickupCodeService, "repo", repo), \
         patch.object(svc, "require_active_guest"), \
         patch.object(svc, "_assert_has_delivery_role"), \
         patch.object(svc.orderRepository, "find_one", side_effect=lambda f: dict(store["doc"])), \
         patch.object(svc.orderRepository, "edit", side_effect=edit):
        class E:  # noqa: N801
            pass
        e = E()
        e.repo, e.saved, e.fan, e.store = repo, saved, mocks, store
        yield e
    for p in fans.values():
        p.stop()


def _with_code(env):
    return PickupCodeService.assign_code(str(OID))


def test_correct_code_dispatches_and_notifies_the_buyer_and_the_store(env):
    code = _with_code(env)
    result = svc.confirm_pickup(str(OID), guest_token=TOKEN, code=code)
    assert result["status"] == "DISPATCHED"
    assert env.saved["picked_up_via"] == "code"
    assert env.saved["picked_up_at"] is not None
    env.fan["fanout_order_status_change"].assert_called_once()
    assert env.fan["fanout_order_status_change"].call_args.kwargs["new_status"] == "DISPATCHED"
    env.fan["fanout_delivery_handed_off"].assert_called_once()
    assert env.fan["fanout_delivery_handed_off"].call_args.kwargs["unverified"] is False
    assert env.repo.find(str(OID)) is None  # the code is gone once used


def test_wrong_code_returns_tries_left(env):
    _with_code(env)
    with pytest.raises(svc.PickupCodeError) as exc:
        svc.confirm_pickup(str(OID), guest_token=TOKEN, code="0001")
    assert exc.value.status_code == 422
    assert exc.value.code == "wrong_pickup_code"
    assert exc.value.extra["tries_left"] == 4
    assert env.store["doc"]["status"] == "WAITING_FOR_COLLECTION"


def test_locked_after_five_tries(env):
    code = _with_code(env)
    bad = "0001" if code != "0001" else "0002"
    for _ in range(4):
        with pytest.raises(svc.PickupCodeError):
            svc.confirm_pickup(str(OID), guest_token=TOKEN, code=bad)
    with pytest.raises(svc.PickupCodeError) as exc:
        svc.confirm_pickup(str(OID), guest_token=TOKEN, code=bad)
    assert exc.value.status_code == 423 and exc.value.code == "pickup_code_locked"
    assert "retry_at" in exc.value.extra


def test_locked_still_allows_the_photo_escape_hatch(env):
    code = _with_code(env)
    bad = "0001" if code != "0001" else "0002"
    for _ in range(5):
        with pytest.raises(svc.PickupCodeError):
            svc.confirm_pickup(str(OID), guest_token=TOKEN, code=bad)
    result = svc.confirm_pickup(str(OID), guest_token=TOKEN, photo_urls=["pickup.jpg"])
    assert result["status"] == "DISPATCHED"


def test_photo_without_code_flags_rider_unverified_and_alerts_the_store(env):
    _with_code(env)
    svc.confirm_pickup(str(OID), guest_token=TOKEN, photo_urls=["pickup.jpg"], notes="Atendían a otro cliente")
    assert env.saved["picked_up_via"] == "rider_unverified"
    assert env.saved["pickup_pictures_seller"] == ["pickup.jpg"]
    assert env.saved["pickup_notes_seller"] == "Atendían a otro cliente"
    assert env.fan["fanout_delivery_handed_off"].call_args.kwargs["unverified"] is True
    env.fan["fanout_order_status_change"].assert_called_once()


def test_no_code_and_no_photo_is_400(env):
    _with_code(env)
    with pytest.raises(HTTPException) as exc:
        svc.confirm_pickup(str(OID), guest_token=TOKEN)
    assert exc.value.status_code == 400


def test_another_rider_is_403(env):
    code = _with_code(env)
    with pytest.raises(HTTPException) as exc:
        svc.confirm_pickup(str(OID), guest_token="someone-else", code=code)
    assert exc.value.status_code == 403


def test_order_not_waiting_for_collection_is_409(env):
    code = _with_code(env)
    env.store["doc"] = _doc(status="DISPATCHED")
    with pytest.raises(HTTPException) as exc:
        svc.confirm_pickup(str(OID), guest_token=TOKEN, code=code)
    assert exc.value.status_code == 409


def test_legacy_order_without_a_code_confirms_as_before(env):
    result = svc.confirm_pickup(str(OID), guest_token=TOKEN)
    assert result["status"] == "DISPATCHED"
    assert env.saved["picked_up_via"] is None
    env.fan["fanout_delivery_handed_off"].assert_not_called()


def test_account_rider_can_confirm_pickup(env):
    code = _with_code(env)
    env.store["doc"] = _doc(assignment=MEMBER)
    result = svc.confirm_pickup(str(OID), user_uid="rider-1", code=code)
    assert result["status"] == "DISPATCHED"
    assert env.saved["picked_up_by"]["type"] == "rider"


def test_account_rider_who_is_not_assigned_is_403(env):
    code = _with_code(env)
    env.store["doc"] = _doc(assignment=MEMBER)
    with pytest.raises(HTTPException) as exc:
        svc.confirm_pickup(str(OID), user_uid="rider-2", code=code)
    assert exc.value.status_code == 403


def test_the_result_never_contains_the_code(env):
    code = _with_code(env)
    result = svc.confirm_pickup(str(OID), guest_token=TOKEN, code=code)
    assert "pickup_code" not in result


# ── route ────────────────────────────────────────────────────────────────────

import main  # noqa: E402
from tests.asgi_client import AsgiClient  # noqa: E402


@pytest.fixture
def api(env):
    async def account(request):
        request.state.user = {"uid": "rider-1"}
        request.state.groupSelected = SELLER
        return request.state.user

    with patch.object(main, "verify_token", side_effect=account):
        yield AsgiClient(main.app), env


def test_route_wrong_code_answers_422_with_tries_left(api):
    client, env = api
    _with_code(env)
    res = client.post("/delivery/confirm-pickup", headers={"X-Guest-Token": TOKEN}, json={"order_id": str(OID), "code": "0001"})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "wrong_pickup_code" and body["tries_left"] == 4


def test_route_without_any_credentials_is_401(api):
    client, env = api
    with patch.object(main, "verify_token", side_effect=main.HTTPException(status_code=401, detail="no")):
        res = client.post("/delivery/confirm-pickup", json={"order_id": str(OID), "code": "1234"})
    assert res.status_code == 401


def test_route_old_client_field_names_still_work(api):
    client, env = api
    _with_code(env)
    res = client.post("/delivery/confirm-pickup", headers={"X-Guest-Token": TOKEN},
                      json={"order_id": str(OID), "delivery_pictures_seller": ["old.jpg"], "delivery_notes_seller": "nota"})
    assert res.status_code == 200
    assert env.saved["pickup_pictures_seller"] == ["old.jpg"]
    assert env.saved["picked_up_via"] == "rider_unverified"


def test_route_account_rider_confirms_with_the_code(api):
    client, env = api
    code = _with_code(env)
    env.store["doc"] = _doc(assignment=MEMBER)
    res = client.post("/delivery/confirm-pickup", json={"order_id": str(OID), "code": code})
    assert res.status_code == 200
    assert res.json()["body"]["status"] == "DISPATCHED"
