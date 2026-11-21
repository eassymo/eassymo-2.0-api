"""Alert copy for the handoff and the issues: Spanish texts, wording by pickup state, who gets a push."""
from unittest.mock import patch

import pytest

from app.services import NotificationService, notification_fanout as fanout
from tests.test_delivery_fanout import ACCOUNT, BUYER, GUEST, ORDER_ID, SELLER, TOKEN, _order

SELLER_USERS = [{"_id": SELLER, "users": ["owner-uid"]}]
BUYER_USERS = [{"_id": BUYER, "users": ["buyer-uid"]}]
CODE = "4827"


@pytest.fixture
def sent():
    stored, pushes = [], []

    def insert_many(docs):
        out = [{**d, "_id": f"n{i}"} for i, d in enumerate(docs)]
        stored.extend(out)
        return out

    def groups(ids):
        return [g for g in SELLER_USERS + BUYER_USERS if g["_id"] in ids]

    with patch.object(NotificationService.notificationRepository, "insert_many", side_effect=insert_many), \
         patch.object(NotificationService.realtime_bus, "publish_inbox_event"), \
         patch.object(NotificationService.push_service, "send_push_from_notification",
                      side_effect=lambda doc: pushes.append(doc)), \
         patch.object(fanout, "_user_name", return_value="Carla"), \
         patch.object(fanout, "_users_by_group_ids", side_effect=groups):
        yield stored, pushes


def _texts(stored):
    return [(n["type"], n["metaData"]["title"], n["metaData"]["body"]) for n in stored]


def test_ready_alert_tells_the_rider_to_ask_for_the_code(sent):
    stored, _ = sent
    fanout.fanout_delivery_ready(order=_order(ACCOUNT))
    assert _texts(stored) == [("DELIVERY_READY", "Ya está lista",
                               "Balata delantera en Refacciones Lupita. Pídele el código al encargado de la tienda.")]


def test_canceled_before_pickup_says_no_la_recojas(sent):
    stored, _ = sent
    fanout.fanout_delivery_canceled(order=_order(ACCOUNT))
    assert stored[0]["metaData"]["body"].endswith("No la recojas.")


def test_canceled_after_pickup_says_devuelvela_a_la_tienda(sent):
    stored, _ = sent
    fanout.fanout_delivery_canceled(order=_order(ACCOUNT, picked_up_at="2026-11-21T20:00:00Z"))
    assert stored[0]["metaData"]["body"].endswith("Devuélvela a la tienda.")
    assert "No la recojas" not in stored[0]["metaData"]["body"]


def test_handed_off_tells_the_store_and_flags_an_unverified_pickup(sent):
    stored, _ = sent
    fanout.fanout_delivery_handed_off(order=_order(ACCOUNT, picked_up_at="2026-11-21T20:00:00Z"))
    fanout.fanout_delivery_handed_off(order=_order(ACCOUNT), unverified=True)
    assert [t[0] for t in _texts(stored)] == ["DELIVERY_HANDED_OFF"] * 2
    assert _texts(stored)[1][1] == "Recogida sin código"
    assert {n["owner"] for n in stored} == {"owner-uid"}


def test_issue_alerts_the_store_and_for_a_delivery_the_buyer(sent):
    stored, _ = sent
    fanout.fanout_delivery_issue(order=_order(ACCOUNT), failure={"kind": "delivery", "reason": "no_answer"})
    by_owner = {n["owner"]: n for n in stored}
    assert set(by_owner) == {"owner-uid", "buyer-uid"}
    assert by_owner["owner-uid"]["metaData"]["title"] == "No se pudo entregar"
    assert by_owner["owner-uid"]["metaData"]["body"] == "Balata delantera: no contestan."
    assert by_owner["buyer-uid"]["metaData"]["title"] == "No pudimos entregar tu pedido"
    assert all(n["type"] == "DELIVERY_ISSUE" for n in stored)


def test_a_pickup_issue_only_alerts_the_store(sent):
    stored, _ = sent
    fanout.fanout_delivery_issue(order=_order(ACCOUNT), failure={"kind": "pickup", "reason": "store_closed"})
    assert [(n["owner"], n["metaData"]["title"], n["metaData"]["body"]) for n in stored] == [
        ("owner-uid", "No se pudo recoger", "Balata delantera: la tienda está cerrada.")]


@pytest.mark.parametrize("action,role,rider_body", [
    ("fix_and_retry", "buyer", "El comprador corrigió los datos. Intenta de nuevo."),
    ("return_to_store", "store", "Devuelve el paquete a la tienda."),
])
def test_resolution_texts_for_the_rider(sent, action, role, rider_body):
    stored, _ = sent
    fanout.fanout_issue_resolved(order=_order(ACCOUNT), action=action, resolution={"by": {"role": role}})
    rider = [n for n in stored if n["owner"] == "rider-uid"]
    assert rider and rider[0]["metaData"]["body"] == rider_body


def test_resolution_tells_the_party_that_did_not_act(sent):
    stored, _ = sent
    fanout.fanout_issue_resolved(order=_order(ACCOUNT), action="fix_and_retry", resolution={"by": {"role": "buyer"}})
    assert {n["owner"] for n in stored} == {"rider-uid", "owner-uid"}
    stored.clear()
    fanout.fanout_issue_resolved(order=_order(ACCOUNT, to_be_delivered_time="2026-11-19T20:49:00.000Z"),
                                 action="reschedule", resolution={"by": {"role": "store"}})
    assert {n["owner"] for n in stored} == {"rider-uid", "buyer-uid"}


def test_account_riders_get_push_and_guests_the_in_app_feed_only(sent):
    stored, pushes = sent
    fanout.fanout_issue_resolved(order=_order(ACCOUNT), action="return_to_store", resolution={"by": {"role": "store"}})
    assert [p["owner"] for p in pushes if p["owner"] == "rider-uid"] == ["rider-uid"]
    stored.clear(); pushes.clear()
    fanout.fanout_issue_resolved(order=_order(GUEST), action="return_to_store", resolution={"by": {"role": "store"}})
    guest = [n for n in stored if n.get("guest_token") == TOKEN]
    assert len(guest) == 1 and guest[0]["owner"] == ""
    assert not [p for p in pushes if p.get("guest_token") == TOKEN]


def test_guessing_alert_goes_to_the_store_without_the_code(sent):
    stored, _ = sent
    with patch("app.repositories.OrderRepository.find_one", return_value={**_order(ACCOUNT), "_id": __import__("bson").ObjectId(ORDER_ID)}):
        fanout.fanout_pickup_code_guessing(order_id=ORDER_ID)
    assert [n["owner"] for n in stored] == ["owner-uid"]
    assert stored[0]["metaData"]["title"] == "Código de recogida bloqueado"


def test_no_alert_body_contains_a_code(sent):
    stored, _ = sent
    order = _order(ACCOUNT, pickup_code=CODE, picked_up_at="2026-11-21T20:00:00Z")
    fanout.fanout_delivery_assigned(order=order)
    fanout.fanout_delivery_ready(order=order)
    fanout.fanout_delivery_handed_off(order=order)
    fanout.fanout_delivery_handed_off(order=order, unverified=True)
    fanout.fanout_delivery_issue(order=order, failure={"kind": "delivery", "reason": "other", "note": "x"})
    fanout.fanout_issue_resolved(order=order, action="fix_and_retry", resolution={"by": {"role": "buyer"}})
    fanout.fanout_delivery_canceled(order=order)
    assert stored and CODE not in str([(n["message"], n["metaData"]) for n in stored])
