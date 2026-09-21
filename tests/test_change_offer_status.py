from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.Offer import OfferStatus
from app.schemas.PartRequest import PartRequestStatus
from app.services import OfferService as svc


def _part_request_doc(request_id: str = "req-1") -> dict:
    return {
        "_id": request_id,
        "creatorGroup": "buyer-1",
        "creatorUser": "user-1",
        "vehicleId": "veh-1",
        "isActive": True,
        "partList": [],
        "status": PartRequestStatus.CREATED.value,
        "part": {"tipoParteDescripcion": "Balata"},
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }


def _offer_doc(offer_id: str = "offer-1", request_id: str = "req-1") -> dict:
    return {
        "_id": offer_id,
        "request_id": request_id,
        "user_uid": "seller-user",
        "group_id": "seller-1",
        "unit_of_measure": "Pieza",
        "status": OfferStatus.created.value,
        "brand": "FRITEC",
        "code": "455",
        "price": 500,
        "guarantee": "60 KM",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }


@patch("app.services.OfferService.orderRepository.find_one")
@patch("app.services.OfferService._get_offer_data")
@patch("app.services.OfferService._get_part_request_data")
def test_change_offer_status_selected_is_idempotent_for_same_offer(
    mock_get_part_request,
    mock_get_offer,
    mock_find_order,
):
    mock_get_part_request.return_value = MagicMock(
        status=PartRequestStatus.OFFER_SELECTED,
        update_status=MagicMock(),
        toJson=MagicMock(return_value=_part_request_doc()),
    )
    mock_get_offer.return_value = MagicMock(
        status=OfferStatus.selected,
        update_status=MagicMock(),
        toJson=MagicMock(return_value=_offer_doc()),
    )
    mock_find_order.return_value = {
        "_id": "order-1",
        "offer": {"_id": "offer-1"},
    }

    result = svc.change_offer_status("req-1", "offer-1", "selected", "token")

    assert result["order_id"] == "order-1"


@patch("app.services.OfferService.orderRepository.find_one")
@patch("app.services.OfferService._get_offer_data")
@patch("app.services.OfferService._get_part_request_data")
def test_change_offer_status_selected_rejects_duplicate_order_for_request(
    mock_get_part_request,
    mock_get_offer,
    mock_find_order,
):
    mock_get_part_request.return_value = MagicMock(
        status=PartRequestStatus.OFFER_SELECTED,
        update_status=MagicMock(),
        toJson=MagicMock(return_value=_part_request_doc()),
    )
    mock_get_offer.return_value = MagicMock(
        status=OfferStatus.created,
        update_status=MagicMock(),
        toJson=MagicMock(return_value=_offer_doc(offer_id="offer-2")),
    )
    mock_find_order.return_value = {
        "_id": "order-1",
        "offer": {"_id": "offer-1"},
    }

    with pytest.raises(HTTPException) as exc:
        svc.change_offer_status("req-1", "offer-2", "selected", "token")

    assert exc.value.status_code == 409


@patch("app.services.OfferService.orderRepository.find_one", return_value=None)
@patch("app.services.OfferService._get_offer_data")
@patch("app.services.OfferService._get_part_request_data")
def test_change_offer_status_selected_rejects_already_selected_offer(
    mock_get_part_request,
    mock_get_offer,
    mock_find_order,
):
    mock_get_part_request.return_value = MagicMock(
        status=PartRequestStatus.CREATED,
        update_status=MagicMock(),
        toJson=MagicMock(return_value=_part_request_doc()),
    )
    mock_get_offer.return_value = MagicMock(
        status=OfferStatus.selected,
        update_status=MagicMock(),
        toJson=MagicMock(return_value=_offer_doc()),
    )

    with pytest.raises(HTTPException) as exc:
        svc.change_offer_status("req-1", "offer-1", "selected", "token")

    assert exc.value.status_code == 409
