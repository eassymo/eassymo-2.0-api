"""Fixes from the final review: canceled orders stay canceled, the buyer's orders carry the cancel, quote decisions close with the request."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import NotificationService, OrderService, PartRequestService, OfferService as offer_svc
from app.repositories import OrderRepository as repo
from tests.test_report_failed_delivery import OID, _doc


def _db():
    coll = MagicMock()
    return MagicMock(__getitem__=lambda self, n: coll), coll


@pytest.mark.parametrize("new_status", ["CONFIRMED", "READY_TO_BE_DISPATCHED", "DISPATCHED", "RECIEVED"])
def test_a_canceled_order_cannot_move_again(new_status):
    doc = _doc(status="CANCELED")
    doc["status_history"] = []
    with patch.object(OrderService.orderRepository, "find_by_id", return_value=[doc]), \
         patch.object(OrderService.orderRepository, "edit") as edit:
        with pytest.raises(HTTPException) as exc:
            OrderService.change_order_status(str(OID), new_status, None, None, None)
    assert exc.value.status_code == 409 and exc.value.detail == "Esta orden ya fue cancelada."
    edit.assert_not_called()


def test_a_save_that_lost_the_race_to_a_cancel_is_a_409():
    doc = _doc(status="WAITING_FOR_CONFIRMATION")
    doc["status_history"] = []
    with patch.object(OrderService.orderRepository, "find_by_id", return_value=[doc]), \
         patch.object(OrderService.orderRepository, "edit", return_value=None) as edit, \
         patch("app.services.notification_fanout.fanout_order_status_change") as fanout:
        with pytest.raises(HTTPException) as exc:
            OrderService.change_order_status(str(OID), "CONFIRMED", None, None, None)
    assert exc.value.status_code == 409
    assert edit.call_args.kwargs.get("unless_canceled") is True
    fanout.assert_not_called()


def test_edit_unless_canceled_filters_on_status():
    fake, coll = _db()
    with patch.object(repo.database, "db", fake):
        repo.edit(OID, {"status": "CONFIRMED"}, unless_canceled=True)
        repo.edit(OID, {"status": "CONFIRMED"})
    assert coll.find_one_and_update.call_args_list[0].args[0] == {"_id": OID, "status": {"$ne": "CANCELED"}}
    assert coll.find_one_and_update.call_args_list[1].args[0] == {"_id": OID}


def test_clear_request_cancellation_updates_every_order_of_the_request():
    fake, coll = _db()
    with patch.object(repo.database, "db", fake):
        repo.clear_request_cancellation("req-1")
        repo.clear_request_cancellation("req-1", closed=True)
    (query, update), _ = coll.update_many.call_args_list[0]
    assert query == {"$or": [{"part_request._id": "req-1"}, {"part_request.id": "req-1"}]}
    assert update == {"$set": {"part_request.last_cancellation": None}}
    assert coll.update_many.call_args_list[1].args[1]["$set"]["part_request.isActive"] is False


def test_resolve_by_decision_prefix():
    fake, coll = _db()
    from app.repositories import NotificationRepository as nrepo
    coll.update_many.return_value.modified_count = 3
    with patch.object(nrepo, "db", fake):
        assert nrepo.resolve_by_decision_prefix("request:r1:quote:", 5) == 3
    query = coll.update_many.call_args.args[0]
    assert query["resolved_at"] is None and query["decision_key"]["$regex"] == "^request:r1:quote:"


def test_closing_a_request_also_closes_the_quote_reminders_and_the_orders_snapshot():
    doc = {"_id": "req-1", "creatorGroup": "b"}
    with patch.object(PartRequestService.partRequestRepository, "find_one_by_id", return_value=doc), \
         patch.object(PartRequestService.partRequestRepository, "edit_part_request"), \
         patch("app.services.PickupCodeService._user_in_group", return_value=True), \
         patch.object(NotificationService, "resolve_decisions"), \
         patch.object(NotificationService, "resolve_decisions_prefix") as prefix, \
         patch("app.repositories.OrderRepository.clear_request_cancellation") as clear:
        PartRequestService.close_part_request("req-1", "u")
    prefix.assert_called_once_with("request:req-1:quote:")
    clear.assert_called_once_with("req-1", closed=True)


def test_error_message_keeps_the_409_text_for_the_client():
    from app.utils.ResponseUtils import error_json_response
    body = error_json_response(HTTPException(status_code=409, detail="La pieza ya salió de la tienda.")).body
    import json
    assert "La pieza ya salió de la tienda." in json.loads(body)["error"]
