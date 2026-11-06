from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.repositories import GroupRepository as groupRepository
from app.repositories import OrderRepository as orderRepository
from app.repositories import ReviewRepository as reviewRepository
from app.schemas.Order import Order, OrderStatus
from app.schemas.Review import (
    DisputeStatus,
    GroupReview,
    OpenDisputeRequest,
    ResolveDisputeRequest,
    ReviewDispute,
    ReviewerRole,
    ReviewStatus,
    ReviewSubRatings,
    ReputationSummary,
    SubmitReviewRequest,
    TransactionType,
)

REVIEW_SUBMISSION_DAYS = 30
REVEAL_WINDOW_DAYS = 14
COMPLETED_STATUSES = {
    OrderStatus.RECIEVED.value,
    OrderStatus.IN_PERSON_COMPLETED.value,
}
SUB_RATING_KEYS = (
    "communication",
    "timeliness",
    "as_described",
    "part_correct",
    "on_time",
    "handoff",
    "request_clarity",
    "reliable_pickup",
)
BUYER_SUB_KEYS = frozenset({"part_correct", "on_time", "handoff"})
SELLER_SUB_KEYS = frozenset({"request_clarity", "reliable_pickup", "handoff"})
LEGACY_MAP_BUYER = {
    "communication": "handoff",
    "timeliness": "on_time",
    "as_described": "part_correct",
}
LEGACY_MAP_SELLER = {
    "communication": "handoff",
    "timeliness": "reliable_pickup",
    "as_described": "request_clarity",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except InvalidId as exc:
        raise HTTPException(status_code=400, detail="Invalid id") from exc


def _is_valid_object_id(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip()
    if not normalized or normalized.lower() in {"none", "null", "undefined"}:
        return False
    try:
        ObjectId(normalized)
        return True
    except InvalidId:
        return False


def _normalize_group_id(group_id: Optional[Any]) -> Optional[str]:
    if not _is_valid_object_id(group_id):
        return None
    return str(ObjectId(str(group_id).strip()))


def _lookup_id_variants(value: Optional[Any]) -> List[Any]:
    if value is None:
        return []
    normalized = str(value).strip()
    if not normalized or normalized.lower() in {"none", "null", "undefined"}:
        return []
    variants: List[Any] = [normalized]
    try:
        oid = ObjectId(normalized)
        if oid not in variants:
            variants.append(oid)
    except InvalidId:
        pass
    return variants


def _group_field_filter(field: str, group_id: Optional[str]) -> Dict[str, Any]:
    variants = _lookup_id_variants(group_id)
    if not variants:
        return {}
    if len(variants) == 1:
        return {field: variants[0]}
    return {field: {"$in": variants}}


def _canonical_transaction_id(order_doc: dict) -> str:
    order_oid = order_doc.get("_id")
    if order_oid is None:
        raise HTTPException(status_code=400, detail="Order is missing _id")
    return str(order_oid)


def _try_canonical_transaction_id(order_doc: dict) -> Optional[str]:
    order_oid = order_doc.get("_id")
    if order_oid is None:
        return None
    try:
        return str(ObjectId(str(order_oid)))
    except InvalidId:
        return None


def _group_display_name(group_id: Optional[str]) -> Optional[str]:
    gid = _normalize_group_id(group_id)
    if not gid:
        return None
    doc = groupRepository.find_by_id(gid, {"name": 1, "type": 1})
    return doc.get("name") if doc else None


def _find_order_doc_for_review(transaction_id: str) -> Optional[dict]:
    txn = transaction_id.strip()
    if not txn:
        return None
    try:
        doc = orderRepository.find_one({"_id": ObjectId(txn)})
        if doc:
            return doc
    except InvalidId:
        pass
    return orderRepository.find_one({"order_id": txn})


def _normalize_sub_ratings(
    sub_ratings: Optional[ReviewSubRatings],
    reviewer_role: ReviewerRole,
) -> Optional[dict]:
    if sub_ratings is None:
        return None
    raw = sub_ratings.model_dump(exclude_none=True)
    if not raw:
        return None

    allowed = BUYER_SUB_KEYS if reviewer_role == ReviewerRole.BUYER else SELLER_SUB_KEYS
    legacy_map = LEGACY_MAP_BUYER if reviewer_role == ReviewerRole.BUYER else LEGACY_MAP_SELLER
    result: Dict[str, int] = {}

    for key, val in raw.items():
        if val is None:
            continue
        if key in allowed:
            result[key] = int(val)
        elif key in legacy_map:
            mapped = legacy_map[key]
            if mapped in allowed and mapped not in result:
                result[mapped] = int(val)

    return result if result else None


def _parse_datetime_value(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace(" ", "T"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None
    return None


def _part_name_from_order_doc(order_doc: dict) -> str:
    offer = order_doc.get("offer") or {}
    part_request = order_doc.get("part_request") or {}
    request_info = offer.get("request_info") or part_request
    part = request_info.get("part") if isinstance(request_info, dict) else None
    if isinstance(part, str):
        return part or "Pedido"
    if isinstance(part, dict):
        return part.get("tipoParteDescripcion") or "Pedido"
    return "Pedido"


def _vehicle_label_from_order_doc(order_doc: dict) -> Optional[str]:
    offer = order_doc.get("offer") or {}
    part_request = order_doc.get("part_request") or {}
    request_info = offer.get("request_info") or part_request
    vehicle = {}
    if isinstance(request_info, dict):
        vehicle = request_info.get("vehicleInformation") or {}
    if not vehicle and isinstance(part_request, dict):
        vehicle = part_request.get("vehicleInformation") or {}
    if not isinstance(vehicle, dict):
        return None
    label = f"{vehicle.get('maker', '')} {vehicle.get('model', '')} {vehicle.get('year', '')}".strip()
    return label or None


def _fulfillment_from_order_doc(order_doc: dict) -> str:
    if _transaction_type_from_doc(order_doc) == TransactionType.MOSTRADOR:
        return "mostrador"
    part_request = order_doc.get("part_request") or {}
    if isinstance(part_request, dict) and part_request.get("fulfillment_type") == "pickup":
        return "pickup"
    return "delivery"


def _build_deal_snapshot(order_doc: dict) -> dict:
    offer = order_doc.get("offer") or {}
    completed_at = _order_completed_at_from_doc(order_doc)
    promised_at = _parse_datetime_value(order_doc.get("to_be_delivered_time"))
    origin = (
        "mostrador"
        if _transaction_type_from_doc(order_doc) == TransactionType.MOSTRADOR
        else "marketplace"
    )
    return {
        "part_name": _part_name_from_order_doc(order_doc),
        "vehicle_label": _vehicle_label_from_order_doc(order_doc),
        "price": offer.get("price") if isinstance(offer, dict) else None,
        "promised_at": promised_at.isoformat() if promised_at else None,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "origin": origin,
        "fulfillment": _fulfillment_from_order_doc(order_doc),
    }


def _user_uid_in_group(user_uid: str, group_id: str | None) -> bool:
    if not user_uid or not group_id:
        return False
    try:
        group_doc = groupRepository.find_users_by_group_id(str(group_id))
    except Exception:
        return False
    if not group_doc or "users" not in group_doc:
        return False
    return user_uid in group_doc.get("users", [])


def _order_from_doc(order_doc: dict) -> Order:
    return Order(**order_doc)


def _get_order_participants_from_doc(order_doc: dict) -> Tuple[Optional[str], Optional[str]]:
    offer = order_doc.get("offer") or {}
    part_request = order_doc.get("part_request") or {}
    buyer_group_id = _normalize_group_id(order_doc.get("group"))
    if not buyer_group_id and isinstance(part_request, dict):
        buyer_group_id = _normalize_group_id(part_request.get("creatorGroup"))
    seller_group_id = _normalize_group_id(offer.get("group_id")) if isinstance(offer, dict) else None
    return buyer_group_id, seller_group_id


def _order_status_value(order_doc: dict) -> str:
    status_val = order_doc.get("status")
    if hasattr(status_val, "value"):
        return status_val.value
    return str(status_val or "")


def _is_order_reviewable_doc(order_doc: dict) -> bool:
    return _order_status_value(order_doc) in COMPLETED_STATUSES


def _order_completed_at_from_doc(order_doc: dict) -> Optional[datetime]:
    target_statuses = COMPLETED_STATUSES
    completed_at: Optional[datetime] = None
    for change in order_doc.get("status_history") or []:
        status_val = change.get("status")
        if hasattr(status_val, "value"):
            status_val = status_val.value
        if status_val in target_statuses:
            ts = change.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace(" ", "T"))
                except ValueError:
                    continue
            if ts and getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts and (completed_at is None or ts > completed_at):
                completed_at = ts
    if completed_at:
        return completed_at
    if _order_status_value(order_doc) in target_statuses:
        updated = order_doc.get("updated_at")
        if isinstance(updated, str):
            try:
                updated = datetime.fromisoformat(updated.replace(" ", "T"))
            except ValueError:
                return None
        if updated and getattr(updated, "tzinfo", None) is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return updated
    return None


def _transaction_type_from_doc(order_doc: dict) -> TransactionType:
    if order_doc.get("origin") == "mostrador" or order_doc.get("mostrador_folio_id"):
        return TransactionType.MOSTRADOR
    return TransactionType.ORDER


def _get_order_participants(order: Order) -> Tuple[Optional[str], Optional[str]]:
    buyer_group_id = order.group
    seller_group_id = None
    if order.offer:
        seller_group_id = order.offer.group_id
    if not buyer_group_id and order.part_request:
        buyer_group_id = order.part_request.creatorGroup
    return (
        str(buyer_group_id) if buyer_group_id else None,
        str(seller_group_id) if seller_group_id else None,
    )


def _order_completed_at(order: Order) -> Optional[datetime]:
    target_statuses = {OrderStatus.RECIEVED.value, OrderStatus.IN_PERSON_COMPLETED.value}
    completed_at: Optional[datetime] = None
    for change in order.status_history or []:
        status_val = change.status
        if hasattr(status_val, "value"):
            status_val = status_val.value
        if status_val in target_statuses:
            ts = change.timestamp
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace(" ", "T"))
                except ValueError:
                    continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if completed_at is None or ts > completed_at:
                completed_at = ts
    if completed_at:
        return completed_at
    if order.status in target_statuses:
        updated = order.updated_at
        if isinstance(updated, str):
            try:
                updated = datetime.fromisoformat(updated.replace(" ", "T"))
            except ValueError:
                return None
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return updated
    return None


def _is_order_reviewable(order: Order) -> bool:
    status_val = order.status
    if hasattr(status_val, "value"):
        status_val = status_val.value
    return status_val in COMPLETED_STATUSES


def _transaction_type_for_order(order: Order) -> TransactionType:
    if order.origin == "mostrador" or order.mostrador_folio_id:
        return TransactionType.MOSTRADOR
    return TransactionType.ORDER


def _reviewer_role_for_group(group_id: str, buyer_group_id: str, seller_group_id: str) -> ReviewerRole:
    if group_id == buyer_group_id:
        return ReviewerRole.BUYER
    if group_id == seller_group_id:
        return ReviewerRole.SELLER
    raise HTTPException(status_code=403, detail="Group did not participate in this transaction")


def _serialize_review(doc: dict) -> dict:
    if not doc:
        return doc
    return GroupReview(**doc).toJson()


def _serialize_dispute(doc: dict) -> dict:
    if not doc:
        return doc
    return ReviewDispute(**doc).toJson()


def _compute_reputation_summary(reviews: List[dict]) -> ReputationSummary:
    if not reviews:
        return ReputationSummary()

    scores = [int(r["score"]) for r in reviews if r.get("score") is not None]
    score_avg = round(sum(scores) / len(scores), 2) if scores else 0.0

    sub_rating_avgs: Dict[str, float] = {}
    sub_rating_counts: Dict[str, int] = {}
    for key in SUB_RATING_KEYS:
        values = []
        for review in reviews:
            sub = review.get("sub_ratings") or {}
            val = sub.get(key)
            if val is not None:
                values.append(int(val))
        if values:
            sub_rating_counts[key] = len(values)
            sub_rating_avgs[key] = round(sum(values) / len(values), 2)

    return ReputationSummary(
        score_avg=score_avg,
        score_count=len(scores),
        sub_rating_avgs=sub_rating_avgs,
        sub_rating_counts=sub_rating_counts,
    )


def recompute_group_reputation(group_id: str) -> ReputationSummary:
    reviews = reviewRepository.find_reviews_for_reputation(group_id)
    summary = _compute_reputation_summary(reviews)
    groupRepository.edit_group(group_id, {"reputation": summary.model_dump()})
    return summary


def _reveal_transaction_reviews(transaction_id: str) -> List[str]:
    now = _now()
    reviewRepository.reveal_reviews_for_transaction(transaction_id, now)
    affected_group_ids = set()
    for doc in reviewRepository.find_reviews_by_transaction(transaction_id):
        if doc.get("status") == ReviewStatus.VISIBLE.value:
            affected_group_ids.add(doc.get("reviewed_group_id"))
            affected_group_ids.add(doc.get("reviewer_group_id"))
    for gid in affected_group_ids:
        if gid:
            recompute_group_reputation(gid)
    return list(affected_group_ids)


def submit_review(
    *,
    user_uid: str,
    reviewer_group_id: str,
    payload: SubmitReviewRequest,
) -> dict:
    reviewer_group_id = _normalize_group_id(reviewer_group_id)
    if not reviewer_group_id:
        raise HTTPException(status_code=400, detail="Invalid group id")

    if not _user_uid_in_group(user_uid, reviewer_group_id):
        raise HTTPException(status_code=403, detail="User is not a member of the selected group")
    order_doc = _find_order_doc_for_review(payload.transaction_id)
    if not order_doc:
        raise HTTPException(status_code=404, detail="Order not found")

    canonical_transaction_id = _canonical_transaction_id(order_doc)

    if not _is_order_reviewable_doc(order_doc):
        raise HTTPException(status_code=400, detail="Order is not completed and cannot be reviewed")

    buyer_group_id, seller_group_id = _get_order_participants_from_doc(order_doc)
    if not buyer_group_id or not seller_group_id:
        raise HTTPException(status_code=400, detail="Order is missing buyer or seller group")
    if buyer_group_id == seller_group_id:
        raise HTTPException(status_code=400, detail="Cannot review a transaction with the same buyer and seller group")

    if reviewer_group_id not in {buyer_group_id, seller_group_id}:
        raise HTTPException(status_code=403, detail="Selected group did not participate in this transaction")

    completed_at = _order_completed_at_from_doc(order_doc)
    if not completed_at:
        raise HTTPException(status_code=400, detail="Could not determine order completion time")
    if _now() > completed_at + timedelta(days=REVIEW_SUBMISSION_DAYS):
        raise HTTPException(
            status_code=400,
            detail=f"Review window expired ({REVIEW_SUBMISSION_DAYS} days after completion)",
        )

    existing = reviewRepository.find_review_by_transaction_and_reviewer(
        canonical_transaction_id, reviewer_group_id
    )
    if existing:
        raise HTTPException(status_code=409, detail="This group already reviewed this transaction")

    reviewer_role = _reviewer_role_for_group(reviewer_group_id, buyer_group_id, seller_group_id)
    reviewed_group_id = seller_group_id if reviewer_role == ReviewerRole.BUYER else buyer_group_id
    normalized_sub_ratings = _normalize_sub_ratings(payload.sub_ratings, reviewer_role)

    now = _now()
    review = GroupReview(
        transaction_type=_transaction_type_from_doc(order_doc),
        transaction_id=canonical_transaction_id,
        reviewer_group_id=reviewer_group_id,
        reviewer_user_id=user_uid,
        reviewer_role=reviewer_role,
        reviewed_group_id=reviewed_group_id,
        score=payload.score,
        sub_ratings=ReviewSubRatings(**normalized_sub_ratings) if normalized_sub_ratings else None,
        comment=(payload.comment or "").strip() or None,
        status=ReviewStatus.PENDING_REVEAL,
        visibility_deadline=now + timedelta(days=REVEAL_WINDOW_DAYS),
        created_at=now,
        updated_at=now,
    )
    inserted = reviewRepository.insert_review(review.toJson())
    review_id = str(inserted.inserted_id)

    counterpart = reviewRepository.find_counterpart_review(canonical_transaction_id, reviewed_group_id)
    if counterpart:
        _reveal_transaction_reviews(canonical_transaction_id)
    else:
        reviewRepository.update_review(review_id, {"updated_at": now})

    saved = reviewRepository.find_review_by_id(review_id)
    return _serialize_review(saved)


def get_pending_reviews(reviewer_group_id: str) -> List[dict]:
    reviewer_group_id = _normalize_group_id(reviewer_group_id)
    if not reviewer_group_id:
        return []

    cutoff = _now() - timedelta(days=REVIEW_SUBMISSION_DAYS)
    pending: List[dict] = []
    completed_status_filter = {"status": {"$in": list(COMPLETED_STATUSES)}}

    buyer_orders = orderRepository.find(
        {**_group_field_filter("group", reviewer_group_id), **completed_status_filter}
    )
    seller_orders = orderRepository.find(
        {**_group_field_filter("offer.group_id", reviewer_group_id), **completed_status_filter}
    )

    seen_ids = set()
    for order_doc in list(buyer_orders) + list(seller_orders):
        order_id = _try_canonical_transaction_id(order_doc)
        if not order_id or order_id in seen_ids:
            continue
        seen_ids.add(order_id)

        completed_at = _order_completed_at_from_doc(order_doc)
        if not completed_at or completed_at < cutoff:
            continue

        buyer_group_id, seller_group_id = _get_order_participants_from_doc(order_doc)
        if not buyer_group_id or not seller_group_id or buyer_group_id == seller_group_id:
            continue

        if reviewer_group_id not in {buyer_group_id, seller_group_id}:
            continue

        existing = reviewRepository.find_review_by_transaction_and_reviewer(order_id, reviewer_group_id)

        counterpart_group_id = (
            seller_group_id if reviewer_group_id == buyer_group_id else buyer_group_id
        )
        item = {
            "transaction_id": order_id,
            "transaction_type": _transaction_type_from_doc(order_doc).value,
            "completed_at": completed_at.isoformat(),
            "counterpart_group_id": counterpart_group_id,
            "counterpart_group_name": _group_display_name(counterpart_group_id),
            "reviewer_role": (
                ReviewerRole.BUYER.value
                if reviewer_group_id == buyer_group_id
                else ReviewerRole.SELLER.value
            ),
            "deal": _build_deal_snapshot(order_doc),
            "review_state": "submitted" if existing else "pending",
        }
        if existing:
            item["score"] = existing.get("score")
            submitted_at = existing.get("created_at")
            if hasattr(submitted_at, "isoformat"):
                item["submitted_at"] = submitted_at.isoformat()
            elif submitted_at is not None:
                item["submitted_at"] = str(submitted_at)
        pending.append(item)

    pending.sort(key=lambda item: item.get("completed_at", ""), reverse=True)
    return pending


def _serialize_submitted_review(doc: dict) -> dict:
    created_at = doc.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    elif created_at is not None:
        created_at = str(created_at)
    return {
        "transaction_id": str(doc.get("transaction_id")),
        "transaction_type": doc.get("transaction_type"),
        "score": doc.get("score"),
        "reviewer_role": doc.get("reviewer_role"),
        "status": doc.get("status"),
        "created_at": created_at,
    }


def get_submitted_reviews(reviewer_group_id: str) -> List[dict]:
    reviewer_group_id = _normalize_group_id(reviewer_group_id)
    if not reviewer_group_id:
        return []
    since = _now() - timedelta(days=REVIEW_SUBMISSION_DAYS)
    docs = reviewRepository.find_submitted_reviews_by_reviewer_group(
        reviewer_group_id,
        since=since,
    )
    return [_serialize_submitted_review(doc) for doc in docs]


def get_group_reviews(group_id: str, *, page: int = 1, page_size: int = 20) -> dict:
    group_id = _normalize_group_id(group_id)
    if not group_id:
        raise HTTPException(status_code=400, detail="Invalid group id")

    skip = (page - 1) * page_size
    items = reviewRepository.find_visible_reviews_for_group(group_id, skip=skip, limit=page_size)
    total = reviewRepository.count_visible_reviews_for_group(group_id)
    enriched = []
    for doc in items:
        serialized = _serialize_review(doc)
        serialized["reviewer_group_name"] = _group_display_name(serialized.get("reviewer_group_id"))
        enriched.append(serialized)
    return {
        "items": enriched,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size) if total else 0,
    }


def get_group_reputation(group_id: str) -> dict:
    group_id = _normalize_group_id(group_id)
    if not group_id:
        raise HTTPException(status_code=400, detail="Invalid group id")

    group = groupRepository.find_by_id(group_id, {"reputation": 1, "name": 1})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    reputation = group.get("reputation")
    if not reputation:
        summary = recompute_group_reputation(group_id)
        return summary.model_dump()
    return reputation


def open_dispute(
    *,
    review_id: str,
    user_uid: str,
    group_id: str,
    payload: OpenDisputeRequest,
) -> dict:
    review_doc = reviewRepository.find_review_by_id(review_id)
    if not review_doc:
        raise HTTPException(status_code=404, detail="Review not found")

    review = GroupReview(**review_doc)
    if review.reviewed_group_id != group_id:
        raise HTTPException(status_code=403, detail="Only the reviewed group can open a dispute")
    if not _user_uid_in_group(user_uid, group_id):
        raise HTTPException(status_code=403, detail="User is not a member of the selected group")
    if review.status not in {ReviewStatus.VISIBLE, ReviewStatus.DISPUTED}:
        raise HTTPException(status_code=400, detail="Review is not visible and cannot be disputed")

    existing = reviewRepository.find_open_dispute_for_review(review_id)
    if existing:
        raise HTTPException(status_code=409, detail="An open dispute already exists for this review")

    now = _now()
    dispute = ReviewDispute(
        review_id=review_id,
        opened_by_group_id=group_id,
        opened_by_user_id=user_uid,
        reason=payload.reason.strip(),
        status=DisputeStatus.OPEN,
        created_at=now,
        updated_at=now,
    )
    inserted = reviewRepository.insert_dispute(dispute.toJson())
    reviewRepository.update_review(
        review_id,
        {"status": ReviewStatus.DISPUTED.value, "updated_at": now},
    )
    recompute_group_reputation(review.reviewed_group_id)
    saved = reviewRepository.find_dispute_by_id(str(inserted.inserted_id))
    return _serialize_dispute(saved)


def list_disputes(*, page: int = 1, page_size: int = 20, status: Optional[str] = None) -> dict:
    skip = (page - 1) * page_size
    items, total = reviewRepository.list_disputes(status=status, skip=skip, limit=page_size)
    enriched = []
    for dispute_doc in items:
        dispute = _serialize_dispute(dispute_doc)
        review_doc = reviewRepository.find_review_by_id(dispute["review_id"])
        dispute["review"] = _serialize_review(review_doc) if review_doc else None
        enriched.append(dispute)
    return {
        "items": enriched,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size) if total else 0,
    }


def resolve_dispute(
    *,
    admin_uid: str,
    dispute_id: str,
    payload: ResolveDisputeRequest,
) -> dict:
    from app.services.AdminWriteService import AdminWriteService

    dispute_doc = reviewRepository.find_dispute_by_id(dispute_id)
    if not dispute_doc:
        raise HTTPException(status_code=404, detail="Dispute not found")

    dispute = ReviewDispute(**dispute_doc)
    if dispute.status not in {DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW}:
        raise HTTPException(status_code=400, detail="Dispute is already resolved")

    review_doc = reviewRepository.find_review_by_id(dispute.review_id)
    if not review_doc:
        raise HTTPException(status_code=404, detail="Review not found")
    review = GroupReview(**review_doc)

    now = _now()
    review_updates: Dict[str, Any] = {"updated_at": now}
    dispute_status: DisputeStatus

    if payload.action == "uphold":
        review_updates["status"] = ReviewStatus.VISIBLE.value
        dispute_status = DisputeStatus.RESOLVED_UPHELD
    elif payload.action == "hide":
        review_updates["status"] = ReviewStatus.HIDDEN_BY_ADMIN.value
        dispute_status = DisputeStatus.RESOLVED_HIDDEN
    elif payload.action == "edit":
        if payload.score is None:
            raise HTTPException(status_code=400, detail="score is required when editing a review")
        review_updates["score"] = payload.score
        review_updates["sub_ratings"] = (
            payload.sub_ratings.model_dump() if payload.sub_ratings else None
        )
        review_updates["comment"] = (payload.comment or "").strip() or None
        review_updates["status"] = ReviewStatus.VISIBLE.value
        dispute_status = DisputeStatus.RESOLVED_EDITED
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    reviewRepository.update_review(dispute.review_id, review_updates)
    updated_dispute = reviewRepository.update_dispute(
        dispute_id,
        {
            "status": dispute_status.value,
            "admin_notes": (payload.admin_notes or "").strip() or None,
            "assigned_admin_uid": admin_uid,
            "resolved_at": now,
            "updated_at": now,
        },
    )
    recompute_group_reputation(review.reviewed_group_id)

    AdminWriteService._log_action(
        admin_uid=admin_uid,
        action=f"review_dispute_{payload.action}",
        entity_type="ReviewDispute",
        entity_id=dispute_id,
        payload={
            "review_id": dispute.review_id,
            "action": payload.action,
            "admin_notes": payload.admin_notes,
        },
    )

    result = _serialize_dispute(updated_dispute)
    result["review"] = _serialize_review(reviewRepository.find_review_by_id(dispute.review_id))
    return result


def reveal_expired_reviews() -> dict:
    now = _now()
    expired = reviewRepository.find_expired_pending_reviews(now)
    transaction_ids = sorted({doc["transaction_id"] for doc in expired})
    revealed_transactions = 0
    affected_groups: set[str] = set()

    for transaction_id in transaction_ids:
        reviewRepository.reveal_reviews_for_transaction(transaction_id, now)
        revealed_transactions += 1
        for doc in reviewRepository.find_reviews_by_transaction(transaction_id):
            if doc.get("reviewed_group_id"):
                affected_groups.add(doc["reviewed_group_id"])
            if doc.get("reviewer_group_id"):
                affected_groups.add(doc["reviewer_group_id"])

    for group_id in affected_groups:
        recompute_group_reputation(group_id)

    return {
        "revealed_transactions": revealed_transactions,
        "affected_groups": len(affected_groups),
    }
