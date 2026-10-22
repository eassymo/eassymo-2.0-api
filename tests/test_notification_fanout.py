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
