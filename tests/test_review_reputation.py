ORDER_ID = "507f1f77bcf86cd799439011"
REVIEW_ID = "507f1f77bcf86cd799439012"
BUYER_GROUP_ID = "674a11111111111111111111"
SELLER_GROUP_ID = "674a22222222222222222222"

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.Review import (
    GroupReview,
    ReputationSummary,
    ReviewSubRatings,
    ReviewStatus,
    ReviewerRole,
    SubmitReviewRequest,
    TransactionType,
)
from app.services import ReviewService as svc


def test_group_review_to_json_omits_null_id():
    now = datetime.now(timezone.utc)
    review = GroupReview(
        transaction_type=TransactionType.ORDER,
        transaction_id=ORDER_ID,
        reviewer_group_id=BUYER_GROUP_ID,
        reviewer_user_id="user1",
        reviewer_role=ReviewerRole.BUYER,
        reviewed_group_id=SELLER_GROUP_ID,
        score=5,
        status=ReviewStatus.PENDING_REVEAL,
        visibility_deadline=now + timedelta(days=14),
        created_at=now,
        updated_at=now,
    )
    payload = review.toJson()
    assert "_id" not in payload


def test_compute_reputation_summary_empty():
    summary = svc._compute_reputation_summary([])
    assert summary.score_avg == 0.0
    assert summary.score_count == 0


def test_compute_reputation_summary_with_optional_sub_ratings():
    reviews = [
        {"score": 5, "sub_ratings": {"communication": 5, "timeliness": 4}},
        {"score": 3, "sub_ratings": {"communication": 3}},
    ]
    summary = svc._compute_reputation_summary(reviews)
    assert summary.score_avg == 4.0
    assert summary.score_count == 2
    assert summary.sub_rating_avgs["communication"] == 4.0
    assert summary.sub_rating_counts["communication"] == 2
    assert summary.sub_rating_avgs["timeliness"] == 4.0
    assert summary.sub_rating_counts["timeliness"] == 1
    assert "as_described" not in summary.sub_rating_avgs


@patch("app.services.ReviewService.orderRepository.find_one")
@patch("app.services.ReviewService._user_uid_in_group", return_value=True)
@patch("app.services.ReviewService.reviewRepository.find_review_by_transaction_and_reviewer", return_value=None)
@patch("app.services.ReviewService.reviewRepository.find_counterpart_review", return_value=None)
@patch("app.services.ReviewService.reviewRepository.insert_review")
@patch("app.services.ReviewService.reviewRepository.find_review_by_id")
@patch("app.services.ReviewService.reviewRepository.update_review")
def test_submit_review_creates_pending_reveal(
    mock_update,
    mock_find_by_id,
    mock_insert,
    mock_counterpart,
    mock_existing,
    mock_member,
    mock_find_order,
):
    now = datetime.now(timezone.utc)
    order_doc = {
        "_id": ORDER_ID,
        "group": BUYER_GROUP_ID,
        "status": "RECIEVED",
        "origin": "marketplace",
        "offer": {"group_id": SELLER_GROUP_ID},
        "part_request": {"creatorGroup": BUYER_GROUP_ID},
        "status_history": [
            {"status": "RECIEVED", "timestamp": now - timedelta(days=1)},
        ],
        "updated_at": now,
        "created_at": now,
    }
    mock_find_order.return_value = order_doc
    inserted = MagicMock()
    inserted.inserted_id = REVIEW_ID
    mock_insert.return_value = inserted
    mock_find_by_id.return_value = {
        "_id": REVIEW_ID,
        "transaction_type": "order",
        "transaction_id": ORDER_ID,
        "reviewer_group_id": BUYER_GROUP_ID,
        "reviewer_user_id": "user1",
        "reviewer_role": "buyer",
        "reviewed_group_id": SELLER_GROUP_ID,
        "score": 5,
        "sub_ratings": None,
        "comment": None,
        "status": "pending_reveal",
        "visibility_deadline": now + timedelta(days=14),
        "revealed_at": None,
        "created_at": now,
        "updated_at": now,
    }

    result = svc.submit_review(
        user_uid="user1",
        reviewer_group_id=BUYER_GROUP_ID,
        payload=SubmitReviewRequest(transaction_id=ORDER_ID, score=5),
    )

    assert result["status"] == "pending_reveal"
    assert result["reviewed_group_id"] == SELLER_GROUP_ID
    mock_insert.assert_called_once()
    insert_payload = mock_insert.call_args[0][0]
    assert "_id" not in insert_payload


@patch("app.services.ReviewService.orderRepository.find_one", return_value=None)
@patch("app.services.ReviewService._user_uid_in_group", return_value=True)
def test_submit_review_order_not_found(mock_member, mock_find_order):
    with pytest.raises(HTTPException) as exc:
        svc.submit_review(
            user_uid="user1",
            reviewer_group_id=BUYER_GROUP_ID,
            payload=SubmitReviewRequest(transaction_id="507f1f77bcf86cd799439099", score=4),
        )
    assert exc.value.status_code == 404


@patch("app.services.ReviewService.orderRepository.find_one")
@patch("app.services.ReviewService._user_uid_in_group", return_value=True)
def test_submit_review_rejects_expired_window(mock_member, mock_find_order):
    now = datetime.now(timezone.utc)
    mock_find_order.return_value = {
        "_id": ORDER_ID,
        "group": BUYER_GROUP_ID,
        "status": "RECIEVED",
        "origin": "marketplace",
        "offer": {"group_id": SELLER_GROUP_ID},
        "part_request": {"creatorGroup": BUYER_GROUP_ID},
        "status_history": [
            {"status": "RECIEVED", "timestamp": now - timedelta(days=31)},
        ],
        "updated_at": now - timedelta(days=31),
        "created_at": now - timedelta(days=40),
    }

    with pytest.raises(HTTPException) as exc:
        svc.submit_review(
            user_uid="user1",
            reviewer_group_id=BUYER_GROUP_ID,
            payload=SubmitReviewRequest(transaction_id=ORDER_ID, score=4),
        )
    assert exc.value.status_code == 400
    assert "expired" in exc.value.detail.lower()


def test_reveal_expired_reviews_updates_groups():
    now = datetime.now(timezone.utc)
    with patch("app.services.ReviewService.reviewRepository.find_expired_pending_reviews") as mock_expired, \
         patch("app.services.ReviewService.reviewRepository.reveal_reviews_for_transaction") as mock_reveal, \
         patch("app.services.ReviewService.reviewRepository.find_reviews_by_transaction") as mock_by_tx, \
         patch("app.services.ReviewService.recompute_group_reputation") as mock_recompute:
        mock_expired.return_value = [{"transaction_id": "tx1"}]
        mock_by_tx.return_value = [
            {"reviewed_group_id": "g1", "reviewer_group_id": "g2", "status": "visible"},
        ]
        result = svc.reveal_expired_reviews()
        assert result["revealed_transactions"] == 1
        assert result["affected_groups"] == 2
        assert mock_recompute.call_count == 2


def test_normalize_sub_ratings_buyer_maps_legacy_keys():
    normalized = svc._normalize_sub_ratings(
        ReviewSubRatings(communication=4, timeliness=3, as_described=5),
        ReviewerRole.BUYER,
    )
    assert normalized == {"handoff": 4, "on_time": 3, "part_correct": 5}


def test_normalize_sub_ratings_seller_maps_legacy_keys():
    normalized = svc._normalize_sub_ratings(
        ReviewSubRatings(communication=2, timeliness=4, as_described=3),
        ReviewerRole.SELLER,
    )
    assert normalized == {"handoff": 2, "reliable_pickup": 4, "request_clarity": 3}


def test_build_deal_snapshot_from_order_doc():
    now = datetime.now(timezone.utc)
    promised = now - timedelta(hours=1)
    order_doc = {
        "_id": ORDER_ID,
        "group": BUYER_GROUP_ID,
        "status": "RECIEVED",
        "origin": "marketplace",
        "to_be_delivered_time": promised,
        "offer": {
            "group_id": SELLER_GROUP_ID,
            "price": 1240.0,
            "request_info": {
                "part": {"tipoParteDescripcion": "Filtro de aceite"},
                "vehicleInformation": {"maker": "Honda", "model": "Civic", "year": "2018"},
            },
        },
        "part_request": {
            "creatorGroup": BUYER_GROUP_ID,
            "fulfillment_type": "delivery",
        },
        "status_history": [{"status": "RECIEVED", "timestamp": now}],
        "updated_at": now,
    }
    snapshot = svc._build_deal_snapshot(order_doc)
    assert snapshot["part_name"] == "Filtro de aceite"
    assert snapshot["vehicle_label"] == "Honda Civic 2018"
    assert snapshot["price"] == 1240.0
    assert snapshot["origin"] == "marketplace"
    assert snapshot["fulfillment"] == "delivery"
    assert snapshot["promised_at"] is not None
    assert snapshot["completed_at"] is not None


@patch("app.services.ReviewService.orderRepository.find")
@patch("app.services.ReviewService.groupRepository.find_by_id", return_value={"name": "Refa Test"})
@patch("app.services.ReviewService.reviewRepository.find_review_by_transaction_and_reviewer", return_value=None)
def test_get_pending_reviews_includes_deal_snapshot(mock_existing, mock_group, mock_find):
    now = datetime.now(timezone.utc)
    order_doc = {
        "_id": ORDER_ID,
        "group": BUYER_GROUP_ID,
        "status": "RECIEVED",
        "origin": "mostrador",
        "offer": {
            "group_id": SELLER_GROUP_ID,
            "price": 500.0,
            "request_info": {"part": {"tipoParteDescripcion": "Balata"}},
        },
        "part_request": {"creatorGroup": BUYER_GROUP_ID},
        "status_history": [{"status": "RECIEVED", "timestamp": now - timedelta(days=1)}],
        "updated_at": now,
    }
    mock_find.side_effect = [[order_doc], []]
    pending = svc.get_pending_reviews(BUYER_GROUP_ID)
    assert len(pending) == 1
    assert pending[0]["review_state"] == "pending"
    assert pending[0]["deal"]["part_name"] == "Balata"
    assert pending[0]["deal"]["origin"] == "mostrador"
    assert pending[0]["deal"]["fulfillment"] == "mostrador"


@patch("app.services.ReviewService.reviewRepository.find_submitted_reviews_by_reviewer_group")
def test_get_submitted_reviews_returns_serialized_items(mock_find):
    now = datetime.now(timezone.utc)
    mock_find.return_value = [
        {
            "transaction_id": ORDER_ID,
            "transaction_type": "order",
            "score": 4,
            "reviewer_role": "seller",
            "status": "pending_reveal",
            "created_at": now,
        }
    ]
    submitted = svc.get_submitted_reviews(SELLER_GROUP_ID)
    assert len(submitted) == 1
    assert submitted[0]["transaction_id"] == ORDER_ID
    assert submitted[0]["score"] == 4
    assert submitted[0]["reviewer_role"] == "seller"


@patch("app.services.ReviewService.orderRepository.find")
@patch("app.services.ReviewService.groupRepository.find_by_id", return_value={"name": "Taller Test"})
@patch("app.services.ReviewService.reviewRepository.find_review_by_transaction_and_reviewer")
def test_get_pending_reviews_includes_submitted_seller_review(mock_existing, mock_group, mock_find):
    now = datetime.now(timezone.utc)
    order_doc = {
        "_id": ORDER_ID,
        "group": BUYER_GROUP_ID,
        "status": "RECIEVED",
        "origin": "marketplace",
        "offer": {"group_id": SELLER_GROUP_ID, "price": 500.0},
        "part_request": {"creatorGroup": BUYER_GROUP_ID},
        "status_history": [{"status": "RECIEVED", "timestamp": now - timedelta(days=1)}],
        "updated_at": now,
    }
    mock_find.side_effect = [[], [order_doc]]
    mock_existing.return_value = {
        "transaction_id": ORDER_ID,
        "reviewer_group_id": SELLER_GROUP_ID,
        "score": 4,
        "created_at": now,
    }
    pending = svc.get_pending_reviews(SELLER_GROUP_ID)
    assert len(pending) == 1
    assert pending[0]["review_state"] == "submitted"
    assert pending[0]["score"] == 4


def test_get_pending_reviews_invalid_reviewer_group_returns_empty():
    assert svc.get_pending_reviews("None") == []
    assert svc.get_pending_reviews("not-an-object-id") == []


@patch("app.services.ReviewService.orderRepository.find")
@patch("app.services.ReviewService.groupRepository.find_by_id", return_value={"name": "Refa Test"})
@patch("app.services.ReviewService.reviewRepository.find_review_by_transaction_and_reviewer", return_value=None)
def test_get_pending_reviews_skips_order_with_invalid_seller_group(mock_existing, mock_group, mock_find):
    now = datetime.now(timezone.utc)
    order_doc = {
        "_id": ORDER_ID,
        "group": BUYER_GROUP_ID,
        "status": "RECIEVED",
        "origin": "marketplace",
        "offer": {"group_id": None},
        "part_request": {"creatorGroup": BUYER_GROUP_ID},
        "status_history": [{"status": "RECIEVED", "timestamp": now - timedelta(days=1)}],
        "updated_at": now,
    }
    mock_find.side_effect = [[order_doc], []]
    pending = svc.get_pending_reviews(BUYER_GROUP_ID)
    assert pending == []
    mock_group.assert_not_called()
