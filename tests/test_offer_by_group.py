"""Unit tests for aggregated group offers."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services import OfferService as svc


def test_find_by_group_seller_only():
    now = datetime.now(timezone.utc)
    seller_doc = {
        "_id": "offer1",
        "request_id": "req1",
        "user_uid": "u1",
        "group_id": "group1",
        "unit_of_measure": "Pieza",
        "internalComments": "",
        "publicComments": "",
        "status": "Created",
        "type": "PartOffer",
        "price": 100.0,
        "createdAt": now,
    }

    with patch("app.services.OfferService.offerRepository.find") as mock_find, \
         patch("app.services.OfferService.partRequestRepository.find") as mock_pr_find, \
         patch("app.services.OfferService.offerRepository.find_by_ids_enriched") as mock_enriched, \
         patch("app.services.OfferService.groupRepository.find_by_id", return_value={"_id": "buyer1", "name": "Buyer"}):
        mock_find.side_effect = [
            [seller_doc],
            [],
        ]
        mock_pr_find.return_value = []
        mock_enriched.return_value = [
            {
                **seller_doc,
                "part_request": {
                    "_id": "req1",
                    "creatorGroup": "buyer1",
                    "status": "CREATED",
                    "part": {"tipoParteDescripcion": "Filtro"},
                    "vehicleInformation": {"model": "Civic"},
                    "createdAt": now,
                },
                "group_info": {"_id": "group1", "name": "Seller"},
            }
        ]

        result = svc.find_by_group("group1", page=1, page_size=10, role="seller")

    assert result["total"] == 1
    assert result["items"][0]["role"] == "seller"
    assert result["items"][0]["price"] == 100.0


def test_find_by_group_buyer_only():
    now = datetime.now(timezone.utc)
    buyer_doc = {
        "_id": "offer2",
        "request_id": "req2",
        "user_uid": "u2",
        "group_id": "seller2",
        "unit_of_measure": "Pieza",
        "internalComments": "",
        "publicComments": "",
        "status": "Created",
        "type": "PartOffer",
        "price": 200.0,
        "createdAt": now,
    }

    with patch("app.services.OfferService.offerRepository.find") as mock_find, \
         patch("app.services.OfferService.partRequestRepository.find") as mock_pr_find, \
         patch("app.services.OfferService.offerRepository.find_by_ids_enriched") as mock_enriched, \
         patch("app.services.OfferService.groupRepository.find_by_id", return_value={"_id": "seller2", "name": "Seller 2"}):
        mock_find.side_effect = [
            [],
            [buyer_doc],
        ]
        mock_pr_find.return_value = [{"_id": "req2"}]
        mock_enriched.return_value = [
            {
                **buyer_doc,
                "part_request": {
                    "_id": "req2",
                    "creatorGroup": "group1",
                    "status": "CREATED",
                    "part": {"tipoParteDescripcion": "Pastillas"},
                    "vehicleInformation": {"model": "Jetta"},
                    "createdAt": now,
                },
                "group_info": {"_id": "seller2", "name": "Seller 2"},
            }
        ]

        result = svc.find_by_group("group1", page=1, page_size=10, role="buyer")

    assert result["total"] == 1
    assert result["items"][0]["role"] == "buyer"


def test_find_by_group_merged_pagination():
    now = datetime.now(timezone.utc)
    older = now.replace(year=now.year - 1)
    seller_doc = {
        "_id": "offerA",
        "request_id": "reqA",
        "user_uid": "u1",
        "group_id": "group1",
        "unit_of_measure": "Pieza",
        "internalComments": "",
        "publicComments": "",
        "status": "Created",
        "type": "PartOffer",
        "price": 50.0,
        "createdAt": older,
    }
    buyer_doc = {
        "_id": "offerB",
        "request_id": "reqB",
        "user_uid": "u2",
        "group_id": "sellerX",
        "unit_of_measure": "Pieza",
        "internalComments": "",
        "publicComments": "",
        "status": "Created",
        "type": "PartOffer",
        "price": 75.0,
        "createdAt": now,
    }

    with patch("app.services.OfferService.offerRepository.find") as mock_find, \
         patch("app.services.OfferService.partRequestRepository.find") as mock_pr_find, \
         patch("app.services.OfferService.offerRepository.find_by_ids_enriched") as mock_enriched, \
         patch("app.services.OfferService.groupRepository.find_by_id", return_value=None):
        mock_find.side_effect = [
            [seller_doc],
            [buyer_doc],
        ]
        mock_pr_find.return_value = [{"_id": "reqB"}]
        mock_enriched.side_effect = lambda ids: [
            {**buyer_doc, "part_request": {"_id": "reqB", "creatorGroup": "group1"}, "group_info": {}}
            if str(ids[0]) == "offerB" or (len(ids) == 1 and str(ids[0]) == "offerB")
            else {**seller_doc, "part_request": {"_id": "reqA", "creatorGroup": "buyer"}, "group_info": {}}
        ]

        result = svc.find_by_group("group1", page=1, page_size=1)

    assert result["total"] == 2
    assert result["total_pages"] == 2
    assert len(result["items"]) == 1
    assert result["items"][0]["_id"] == "offerB"
