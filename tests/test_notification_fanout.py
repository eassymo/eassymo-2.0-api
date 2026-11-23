import sys
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("app.config.database", MagicMock())

from app.services import notification_fanout


def test_fanout_part_request_created_batches_notifications():
    part_requests = [{
        "_id": "pr-1",
        "part": {"tipoParteDescripcion": "Filtro"},
        "subscribedSellers": ["seller-g1"],
    }]

    with patch("app.services.notification_fanout._users_by_group_ids", return_value=[{"_id": "seller-g1", "users": ["u1"]}]), \
         patch("app.services.notification_fanout.callCenterService.get_users_of_callcenters_from_group_ids", return_value=[]), \
         patch("app.services.notification_fanout._group_name", return_value=""), \
         patch("app.services.notification_fanout.send_notifications_batch") as batch:
        notification_fanout.fanout_part_request_created(
            part_requests=part_requests,
            creator_group_name="Taller Demo",
            subscribed_sellers=["seller-g1"],
        )
        batch.assert_called_once()
        assert len(batch.call_args.args[0]) == 1


def test_fanout_offer_after_insert_notifies_buyer():
    part_request = {
        "_id": "pr-1",
        "creatorGroup": "buyer-g1",
        "part": {"tipoParteDescripcion": "Filtro"},
    }
    offer_payload = {
        "status": "Created",
        "group_id": "seller-g1",
        "group_info": {"name": "Refaccionaria Demo"},
    }

    with patch("app.services.notification_fanout._users_by_group_ids", return_value=[{"_id": "buyer-g1", "users": ["u1"]}]), \
         patch("app.services.notification_fanout.send_notifications_batch") as batch:
        notification_fanout.fanout_offer_after_insert(
            offer_payload=offer_payload,
            part_request=part_request,
            offer_id="offer-1",
        )
        batch.assert_called_once()
        assert batch.call_args.args[0][0].type.value == "OFFER_CREATED"


def test_persist_notification_dicts_noop_on_empty():
    with patch("app.services.notification_fanout.send_notifications_batch") as batch:
        notification_fanout.persist_notification_dicts([])
        batch.assert_not_called()


def test_fanout_order_delayed_notifies_buyer_creator():
    order = {
        "_id": "order-1",
        "part_request": {
            "creatorUser": "buyer-u1",
            "creatorGroup": "buyer-g1",
            "part": {"tipoParteDescripcion": "Pastillas"},
        },
        "offer_group": {"name": "Refaccionaria Demo"},
    }

    with patch("app.services.notification_fanout.send_notifications_batch") as batch:
        notification_fanout.fanout_order_delayed(order=order)
        batch.assert_called_once()
        notif = batch.call_args.args[0][0]
        assert notif.type.value == "ORDER_DELAYED"
        assert notif.owner == "buyer-u1"
        assert notif.ownerGroup == "buyer-g1"


def _invite_part(maker="Nissan"):
    return {"vehicleInformation": {"maker": maker, "model": "Altima", "year": "2010"},
            "part": {"tipoParteDescripcion": "Filtro"}}


def _fanout_invite(part_requests):
    with patch("app.services.notification_fanout.send_notifications_batch") as batch:
        notification_fanout.fanout_part_request_invite(
            invite_id="inv-1", inviter_group_name="Taller Hernández", inviter_user="u1",
            owner="o1", owner_group="g1", part_requests=part_requests)
    return batch


def test_part_request_invite_sends_one_notification_for_all_parts():
    parts = [_invite_part(), _invite_part()]
    batch = _fanout_invite(parts)
    batch.assert_called_once()
    sent = batch.call_args.args[0]
    assert len(sent) == 1
    assert sent[0].title == "Taller Hernández te invita a cotizar"
    assert sent[0].body == "2 piezas · Nissan Altima 2010"
    assert sent[0].navigateToUrl == "/join-request-invite/inv-1"
    assert sent[0].metaData == {"partRequests": parts, "partRequest": parts[0]}


def test_part_request_invite_message_singular():
    sent = _fanout_invite([_invite_part()]).call_args.args[0]
    assert sent[0].title == "Taller Hernández te invita a cotizar"
    assert sent[0].body == "1 pieza · Nissan Altima 2010"


def _canceled_order(reason="sold"):
    return {
        "_id": "order-9",
        "offer": {"group_id": "seller-g1"},
        "offer_group": {"name": "AUTOPARTES ALEX"},
        "cancellation": {"by": "seller", "reason": reason},
        "part_request": {
            "_id": "req-7", "creatorGroup": "buyer-g1", "vehicleId": "veh-3",
            "part": {"tipoParteDescripcion": "Conector De La Linea Del Enfriador De Aceite"},
            "vehicleInformation": {"maker": "Jeep", "model": "J10", "year": 1980},
        },
    }


@pytest.mark.parametrize("remaining,body_tail,label", [
    (3, "Tienes 3 ofertas más para elegir.", "Ver otras ofertas (3)"),
    (0, "Envía tu solicitud a más tiendas.", "Ampliar búsqueda"),
])
def test_fanout_order_canceled_tells_only_the_buyer_group(remaining, body_tail, label):
    with patch("app.services.notification_fanout._users_by_group_ids", return_value=[{"_id": "buyer-g1", "users": ["b1", "b2"]}]) as users, \
         patch("app.services.notification_fanout.send_notifications_batch") as batch:
        notification_fanout.fanout_order_canceled(order=_canceled_order(), remaining_offers=remaining)
    users.assert_called_once_with(["buyer-g1"])
    sent = batch.call_args.args[0]
    assert [n.owner for n in sent] == ["b1", "b2"]
    n = sent[0]
    assert n.type.value == "ORDER_CANCELED" and n.side == "buy" and n.vehicle == "Jeep J10 1980"
    assert n.title == "Autopartes Alex canceló tu pedido"
    assert n.body == f"Conector de la linea del enfriador de aceite: ya se vendió. {body_tail}"
    assert n.action == {"label": label, "href": "/request-monitor/veh-3?requestId=req-7"}
    assert n.decision_key == "request:req-7:choose"


def test_received_notifies_the_selling_group_not_the_buyer():
    order = {
        "_id": "order-1", "offer": {"group_id": "seller-g1"}, "offer_group": {"name": "AUTOPARTES ALEX"},
        "request_group": {"name": "TALLER HERNANDEZ"}, "updated_at": "2026-11-23T18:40:00Z",
        "part_request": {"creatorGroup": "buyer-g1", "part": {"tipoParteDescripcion": "Alternador"}},
    }
    with patch("app.services.notification_fanout._users_by_group_ids", return_value=[{"_id": "seller-g1", "users": ["s1"]}]) as users, \
         patch("app.services.notification_fanout.send_notifications_batch") as batch:
        notification_fanout.fanout_order_status_change(order=order, new_status="RECIEVED")
    users.assert_called_once_with(["seller-g1"])
    n = batch.call_args.args[0][0]
    assert (n.title, n.body, n.side, n.ownerGroup) == ("Taller Hernandez recibió su pedido", "Alternador · 12:40 p. m.", "sell", "seller-g1")
