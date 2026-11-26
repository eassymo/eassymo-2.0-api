"""Around a withdrawn offer (moved to OffersArchive, so absent from Offers): a late edit is a clear 404, choosing it is a
409, and the seller's own list tells which order an ordered offer belongs to."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.schemas.Offer import Offer
from app.services import OfferService as svc
from tests.test_withdrawn_offers_hidden_from_buyer import _offer, SELLER, BUYER, REQ


def test_edit_missing_offer_is_404():
    payload = Offer(**{**_offer(SELLER, "BOSCH", "Pending_Changes"), "_id": str(ObjectId())})
    with patch.object(svc.offerRepository, "edit_offer", return_value=None), \
         patch.object(svc.brandService, "insert") as brand:
        with pytest.raises(HTTPException) as exc:
            svc.edit_offer(str(ObjectId()), payload)
    assert (exc.value.status_code, exc.value.detail) == (404, "Esta opción ya no existe.")
    brand.assert_not_called()


def test_selecting_a_withdrawn_offer_is_409():
    orders = MagicMock()
    with patch.object(svc, "_get_part_request_data", return_value=MagicMock()), \
         patch.object(svc, "_get_offer_data", return_value=None), \
         patch.object(svc, "orderRepository", orders):
        with pytest.raises(HTTPException) as exc:
            svc.change_offer_status(REQ, str(ObjectId()), "selected", "tok")
    assert (exc.value.status_code, exc.value.detail) == (409, "Esta oferta ya no está disponible.")
    orders.insert.assert_not_called()


def _seller_list(offers, order):
    request = SimpleNamespace(state=SimpleNamespace(_state={"user": {"uid": "uid"}}))
    with patch.object(svc.partRequestRepository, "find_by_id", return_value=[{"_id": REQ}]), \
         patch.object(svc, "PartRequest", return_value=MagicMock(creatorGroup=BUYER)), \
         patch.object(svc.listService, "get_followers_list", return_value=[]), \
         patch.object(svc, "GroupSchema", return_value=MagicMock(id=SELLER, type=2)), \
         patch.object(svc, "_group_acts_as_callcenter", return_value=False), \
         patch.object(svc.offerRepository, "find_by_request_id_and_group", return_value=[dict(o) for o in offers]), \
         patch.object(svc.groupRepository, "find_by_id", side_effect=[{"name": "g"}] + [None] * len(offers)), \
         patch.object(svc.orderRepository, "find_one", side_effect=lambda q: order):
        return svc.find_by_request_id_and_group(request, REQ, SELLER)


def test_selected_offer_carries_its_order_id():
    chosen = _offer(SELLER, "BOSCH", "Selected")
    order_id = ObjectId()
    result = _seller_list([chosen], {"_id": order_id, "status": "CONFIRMED"})
    assert result[0]["order_id"] == str(order_id)


def test_other_offers_have_no_order_id():
    result = _seller_list([_offer(SELLER, "MONROE", "Created")], {"_id": ObjectId(), "status": "CONFIRMED"})
    assert result[0].get("order_id") is None


# Selection claims the offer before any order exists, so it can't race a withdraw.
from tests.test_reselect_after_cancel import sel  # noqa: E402,F401  (fixture)


def test_selecting_claims_the_offer_before_the_order(sel):
    _, _, orders, _ = sel
    calls = []
    svc.offerRepository.claim_status.side_effect = lambda oid, frm, to: calls.append(("claim", frm, to)) or True
    orders.insert.side_effect = lambda doc: calls.append(("order",)) or MagicMock(inserted_id="order-new")
    svc.change_offer_status("req-1", "offer-b", "selected", "tok")
    assert calls[0] == ("claim", "Created", "Selected")
    assert calls[1] == ("order",)


def test_losing_the_claim_is_409_and_creates_no_order(sel):
    _, pr_repo, orders, _ = sel
    svc.offerRepository.claim_status.return_value = False
    with pytest.raises(HTTPException) as exc:
        svc.change_offer_status("req-1", "offer-b", "selected", "tok")
    assert (exc.value.status_code, exc.value.detail) == (409, "Esta oferta ya no está disponible.")
    orders.insert.assert_not_called()
    pr_repo.edit_part_request.assert_not_called()
