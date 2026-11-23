"""A canceled order no longer blocks choosing another offer; the monitor ignores canceled offers."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.Offer import Offer
from app.schemas.PartRequest import PartRequest
from app.services import OfferService as svc
from app.services import NotificationService, OrderService
from tests.test_change_offer_status import _offer_doc as _base_offer, _part_request_doc


def _offer_doc(offer_id):
    return {**_base_offer(offer_id), "internalComments": "", "publicComments": "", "type": "PartOffer"}

LAST = {"order_id": "o1", "store_group_id": "seller-1", "store_name": "Autopartes Alex", "reason": "sold",
        "note": None, "at": datetime.utcnow()}


def _pr(**extra):
    return PartRequest(**{**_part_request_doc(), "subscribedSellers": ["seller-1"], **extra})


@pytest.fixture
def sel():
    pr_repo, offers, orders = MagicMock(), MagicMock(), MagicMock()
    orders.find_one.return_value = None
    orders.insert.return_value.inserted_id = "order-new"
    holder = {"pr": _pr(last_cancellation=LAST), "offer": Offer(**_offer_doc("offer-b"))}
    with patch.object(svc, "partRequestRepository", pr_repo), patch.object(svc, "offerRepository", offers), \
         patch.object(svc, "orderRepository", orders), \
         patch.object(svc, "_get_part_request_data", side_effect=lambda rid: holder["pr"]), \
         patch.object(svc, "_get_offer_data", side_effect=lambda oid: holder["offer"]), \
         patch.object(svc.groupRepository, "find_by_id", return_value={"name": "Taller"}), \
         patch("app.services.notification_fanout.fanout_offer_selected"), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        yield holder, pr_repo, orders, resolve


def test_canceled_order_does_not_block_reselection(sel):
    _, _, orders, _ = sel
    svc.change_offer_status("req-1", "offer-b", "selected", "tok")
    queries = [c.args[0] for c in orders.find_one.call_args_list]
    assert all(q.get("status") == {"$ne": "CANCELED"} for q in queries)
    orders.insert.assert_called_once()


def test_live_order_still_blocks(sel):
    _, _, orders, _ = sel
    orders.find_one.return_value = {"_id": "o9", "offer": {"_id": "offer-a"}}
    with pytest.raises(HTTPException) as exc:
        svc.change_offer_status("req-1", "offer-b", "selected", "tok")
    assert exc.value.status_code == 409


def test_selecting_clears_last_cancellation_and_resolves_the_decision(sel):
    _, pr_repo, _, resolve = sel
    svc.change_offer_status("req-1", "offer-b", "selected", "tok")
    saved = pr_repo.edit_part_request.call_args.args[1]
    assert saved["last_cancellation"] is None
    resolve.assert_called_once_with("request:req-1:choose")


def test_canceled_twice_then_third_offer_selectable(sel):
    holder, pr_repo, orders, _ = sel
    svc.change_offer_status("req-1", "offer-b", "selected", "tok")  # A was canceled earlier
    # B's seller cancels: request reopens and names store B
    holder["pr"] = _pr(last_cancellation={**LAST, "order_id": "o2", "store_name": "Taller Hernández"})
    holder["offer"] = Offer(**_offer_doc("offer-c"))
    svc.change_offer_status("req-1", "offer-c", "selected", "tok")
    assert orders.insert.call_count == 2
    assert pr_repo.edit_part_request.call_args.args[1]["last_cancellation"] is None


def test_generic_change_status_to_canceled_is_400():
    order = MagicMock(status="CONFIRMED")
    with pytest.raises(HTTPException) as exc:
        OrderService._assert_order_status_transition(order, "CANCELED", "u1")
    assert exc.value.status_code == 400
    assert exc.value.detail == "Para cancelar usa No puedo surtir esta orden."


def test_monitor_groups_ignore_canceled_offers_and_expose_summary():
    pr = _part_request_doc()
    pr["subscribedSellers"] = ["gA", "gB", "gC"]
    offers = {
        "gA": [{"status": "Created", "price": 140.0, "createdAt": datetime(2026, 11, 23, 10)},
               {"status": "Created", "price": 105.0, "createdAt": datetime(2026, 11, 23, 11)}],
        "gB": [{"status": "No_Inventory", "price": 90.0, "createdAt": datetime(2026, 11, 23, 9)}],
        "gC": [{"status": "Rejected", "price": 80.0, "createdAt": datetime(2026, 11, 23, 8)}],
    }
    with patch.object(svc.partRequestRepository, "find_one_by_id", return_value=pr), \
         patch.object(svc.offerRepository, "find_by_request_id_and_group", side_effect=lambda rid, gids: offers[gids[0]]), \
         patch.object(svc.requestStatusByGroupRepository, "find_by_group_and_request_id", return_value=None), \
         patch.object(svc.groupRepository, "find_by_id", side_effect=lambda gid: {"_id": gid, "name": f"Tienda {gid}"}):
        result = svc.find_request_offers_by_groups("req-1")
    # a Rejected offer still counts as offered (buyer-side rejection, e.g. commissioner flow); only No_Inventory leaves
    assert [g["_id"] for g in result["have_offered"]] == ["gA", "gC"]
    summary = result["have_offered"][0]["offer_summary"]

    assert summary["price"] == 105.0 and summary["created_at"].startswith("2026-11-23")
    assert [g["_id"] for g in result["no_stock"]] == ["gB"]
    assert result["rejected"] == []
    assert result["have_not_offered"] == []


def test_selecting_clears_the_cancel_snapshot_on_every_order_of_the_request(sel):
    _, _, orders, _ = sel
    svc.change_offer_status("req-1", "offer-b", "selected", "tok")
    orders.clear_request_cancellation.assert_called_once_with("req-1")
