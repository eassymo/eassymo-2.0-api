"""Each domain event settles the decision notice it was waiting on (exact keys)."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.schemas.Offer import OfferStatus
from app.schemas.RequestStatusByGroup import RequestStatusByGroup
from app.services import NotificationService, RequestStatusByGroupService


def test_no_stock_resolves_the_quote_reminder():
    saved = RequestStatusByGroup(group_id="g1", request_id="r1", status=OfferStatus.no_inventory)
    with patch.object(RequestStatusByGroupService.RequestStatusByGroupRepository, "insert", return_value=saved), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        RequestStatusByGroupService.insert(saved)
    resolve.assert_called_once_with("request:r1:quote:g1")


def test_rejected_update_resolves_the_quote_reminder():
    saved = RequestStatusByGroup(group_id="g1", request_id="r1", status=OfferStatus.rejected)
    with patch.object(RequestStatusByGroupService.RequestStatusByGroupRepository, "update", return_value=saved), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        RequestStatusByGroupService.update("id1", saved)
    resolve.assert_called_once_with("request:r1:quote:g1")


def test_other_statuses_do_not_resolve():
    saved = RequestStatusByGroup(group_id="g1", request_id="r1", status=OfferStatus.created)
    with patch.object(RequestStatusByGroupService.RequestStatusByGroupRepository, "insert", return_value=saved), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        RequestStatusByGroupService.insert(saved)
    resolve.assert_not_called()


def test_creating_an_offer_resolves_the_quote_reminder():
    from app.schemas.Offer import Offer
    from app.services import OfferService as svc
    offer = Offer(request_id="r1", user_uid="u", group_id="g1", unit_of_measure="Pieza",
                  internalComments="", publicComments="", brand="Fritec", guarantee="60 km", status="Created", type="PartOffer", price=10)
    with patch.object(svc, "brandService"), patch.object(svc, "guaranteeService"), \
         patch.object(svc.groupRepository, "find_by_id", return_value=None), \
         patch.object(svc.partRequestRepository, "find_one_by_id", return_value=None), \
         patch.object(svc.offerRepository, "insert", return_value=MagicMock(inserted_id="of1")), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        svc.insert(offer, "tok")
    resolve.assert_called_once_with("request:r1:quote:g1")


@pytest.mark.parametrize("previous", [OfferStatus.pending_approval, OfferStatus.workshop_approval_pending])
def test_offer_leaving_approval_resolves_the_approve_decision(previous):
    from app.services import OfferService as svc
    offer = MagicMock(status=previous, update_status=MagicMock(), toJson=MagicMock(return_value={"_id": "of1", "group_id": "g1", "call_center_that_posted_offer": None}))
    pr = MagicMock(status="Created", commissioner_group=None, creatorGroup="b1", toJson=MagicMock(return_value={}))
    with patch.object(svc, "_get_part_request_data", return_value=pr), patch.object(svc, "_get_offer_data", return_value=offer), \
         patch.object(svc.offerRepository, "edit_offer"), patch("app.services.notification_fanout.fanout_callcenter_offer_approved"), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        svc.change_offer_status("r1", "of1", "created", "tok")
    resolve.assert_any_call("offer:of1:approve")


def test_confirming_an_order_resolves_the_confirm_decision():
    from app.services import OrderService as svc
    from tests.test_report_failed_delivery import OID, _doc
    doc = _doc(status="WAITING_FOR_CONFIRMATION")
    doc["status_history"] = []
    with patch.object(svc.orderRepository, "find_by_id", return_value=[doc]), \
         patch.object(svc.orderRepository, "edit", return_value={**doc, "status": "CONFIRMED"}), \
         patch("app.services.notification_fanout.fanout_order_status_change"), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        svc.change_order_status(str(OID), "CONFIRMED", None, None, None)
    resolve.assert_called_once_with(f"order:{OID}:confirm")


def test_resolving_an_issue_resolves_that_issue_decision():
    from tests.test_resolve_issue import ISSUE, OID, SELLER
    from app.services import IssueResolutionService as svc, PickupCodeService
    from tests.test_report_failed_delivery import _doc
    doc = _doc(status="DISPATCHED", failures=[dict(ISSUE)])
    resolved = {**doc, "delivery_failures": [{**ISSUE, "resolution": {"action": "reschedule"}}]}
    with patch.object(svc.orderRepository, "find_by_id", return_value=[doc]), \
         patch.object(svc.orderRepository, "apply_update", return_value=doc), \
         patch.object(svc.orderRepository, "resolve_delivery_failure", return_value=resolved), \
         patch.object(svc, "_user_in_group", side_effect=lambda uid, g: g == SELLER), \
         patch.object(svc.notification_fanout, "fanout_issue_resolved"), patch.object(PickupCodeService, "delete_code"), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        svc.resolve_issue(str(OID), "return_to_store" if False else "reschedule", "store-uid",
                          new_time="2099-01-01T10:00:00+00:00")
    resolve.assert_called_once_with(f"order:{OID}:issue:{ISSUE['id']}")


@pytest.mark.parametrize("answer", ["ACCEPTED", "REJECTED"])
def test_answering_a_commissioner_invite_resolves_it(answer):
    from app.services import CommissionerInviteService as svc
    request = MagicMock()
    request.state._state = {"user": {"uid": "u1"}, "groupSelected": "inv-g"}
    request.headers = {"Authorization": "Bearer tok"}
    raw = {"_id": "i1", "commissioner_group_id": "c-g", "commissioner_group_name": "Taller", "initiating_user_uid": "u0",
           "invited_group_id": "inv-g", "invited_group_name": "Juan", "census_id": "c1", "status": "PENDING",
           "status_history": [{"status": "PENDING", "timestamp": datetime.utcnow()}]}
    with patch.object(svc.commissionerInviteRepository, "find_by_id", return_value=raw), \
         patch.object(svc.commissionerInviteRepository, "update_by_id"), \
         patch.object(svc, "listsService"), patch.object(svc.groupRepository, "find_users_by_group_id", return_value={"users": []}), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        svc.respond_invite(request, "i1", answer)
    resolve.assert_called_once_with("commissioner_invite:i1")
