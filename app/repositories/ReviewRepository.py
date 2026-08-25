from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, ReturnDocument

from app.config import database

REVIEWS_COLLECTION = "GroupReviews"
DISPUTES_COLLECTION = "ReviewDisputes"

db = database.db


def _lookup_id_variants(value: Optional[str]) -> List[Any]:
    """Match reviews whether ids were stored as strings or ObjectIds."""
    if value is None:
        return []
    normalized = str(value).strip()
    if not normalized:
        return []
    variants: List[Any] = [normalized]
    try:
        oid = ObjectId(normalized)
        if oid not in variants:
            variants.append(oid)
    except InvalidId:
        pass
    return variants


def _review_participant_filter(field: str, value: Optional[str]) -> Dict[str, Any]:
    variants = _lookup_id_variants(value)
    if not variants:
        return {}
    if len(variants) == 1:
        return {field: variants[0]}
    return {field: {"$in": variants}}


def ensure_indexes() -> None:
    reviews = db[REVIEWS_COLLECTION]
    reviews.create_index(
        [("transaction_id", ASCENDING), ("reviewer_group_id", ASCENDING)],
        unique=True,
        name="uniq_transaction_reviewer",
    )
    reviews.create_index(
        [("reviewed_group_id", ASCENDING), ("status", ASCENDING)],
        name="reviewed_group_status",
    )
    reviews.create_index(
        [("status", ASCENDING), ("visibility_deadline", ASCENDING)],
        name="status_visibility_deadline",
    )
    reviews.create_index(
        [("reviewer_group_id", ASCENDING), ("created_at", ASCENDING)],
        name="reviewer_group_created",
    )

    disputes = db[DISPUTES_COLLECTION]
    disputes.create_index([("review_id", ASCENDING)], name="dispute_review_id")
    disputes.create_index([("status", ASCENDING), ("created_at", ASCENDING)], name="dispute_status_created")


def insert_review(review: dict):
    payload = dict(review)
    if payload.get("_id") is None:
        payload.pop("_id", None)
    return db[REVIEWS_COLLECTION].insert_one(payload)


def find_review_by_id(review_id: str):
    return db[REVIEWS_COLLECTION].find_one({"_id": ObjectId(review_id)})


def find_review_by_transaction_and_reviewer(transaction_id: str, reviewer_group_id: str):
    filters: Dict[str, Any] = {}
    filters.update(_review_participant_filter("transaction_id", transaction_id))
    filters.update(_review_participant_filter("reviewer_group_id", reviewer_group_id))
    if not filters:
        return None
    return db[REVIEWS_COLLECTION].find_one(filters)


def find_counterpart_review(transaction_id: str, reviewed_group_id: str):
    filters: Dict[str, Any] = {}
    filters.update(_review_participant_filter("transaction_id", transaction_id))
    filters.update(_review_participant_filter("reviewer_group_id", reviewed_group_id))
    if not filters:
        return None
    return db[REVIEWS_COLLECTION].find_one(filters)


def update_review(review_id: str, payload: Dict[str, Any]):
    return db[REVIEWS_COLLECTION].find_one_and_update(
        {"_id": ObjectId(review_id)},
        {"$set": payload},
        return_document=ReturnDocument.AFTER,
    )


def find_visible_reviews_for_group(
    group_id: str,
    *,
    skip: int = 0,
    limit: int = 20,
) -> List[dict]:
    return list(
        db[REVIEWS_COLLECTION]
        .find({"reviewed_group_id": group_id, "status": "visible"})
        .sort("revealed_at", -1)
        .skip(skip)
        .limit(limit)
    )


def count_visible_reviews_for_group(group_id: str) -> int:
    return db[REVIEWS_COLLECTION].count_documents(
        {"reviewed_group_id": group_id, "status": "visible"}
    )


def find_reviews_for_reputation(group_id: str) -> List[dict]:
    return list(
        db[REVIEWS_COLLECTION].find(
            {"reviewed_group_id": group_id, "status": "visible"},
            {"score": 1, "sub_ratings": 1},
        )
    )


def find_expired_pending_reviews(now) -> List[dict]:
    return list(
        db[REVIEWS_COLLECTION].find(
            {
                "status": "pending_reveal",
                "visibility_deadline": {"$lte": now},
            }
        )
    )


def find_reviews_by_transaction(transaction_id: str) -> List[dict]:
    return list(db[REVIEWS_COLLECTION].find({"transaction_id": transaction_id}))


def reveal_reviews_for_transaction(transaction_id: str, revealed_at) -> int:
    result = db[REVIEWS_COLLECTION].update_many(
        {
            "transaction_id": transaction_id,
            "status": "pending_reveal",
        },
        {
            "$set": {
                "status": "visible",
                "revealed_at": revealed_at,
                "updated_at": revealed_at,
            }
        },
    )
    return result.modified_count


def insert_dispute(dispute: dict):
    payload = dict(dispute)
    if payload.get("_id") is None:
        payload.pop("_id", None)
    return db[DISPUTES_COLLECTION].insert_one(payload)


def find_dispute_by_id(dispute_id: str):
    return db[DISPUTES_COLLECTION].find_one({"_id": ObjectId(dispute_id)})


def find_open_dispute_for_review(review_id: str):
    return db[DISPUTES_COLLECTION].find_one(
        {
            "review_id": review_id,
            "status": {"$in": ["open", "under_review"]},
        }
    )


def update_dispute(dispute_id: str, payload: Dict[str, Any]):
    return db[DISPUTES_COLLECTION].find_one_and_update(
        {"_id": ObjectId(dispute_id)},
        {"$set": payload},
        return_document=ReturnDocument.AFTER,
    )


def list_disputes(
    *,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[List[dict], int]:
    filters: Dict[str, Any] = {}
    if status:
        filters["status"] = status
    total = db[DISPUTES_COLLECTION].count_documents(filters)
    items = list(
        db[DISPUTES_COLLECTION]
        .find(filters)
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    return items, total


def find_review_ids_for_group(group_id: str) -> List[str]:
    return [
        str(doc["_id"])
        for doc in db[REVIEWS_COLLECTION].find(
            {"reviewer_group_id": group_id},
            {"_id": 1},
        )
    ]


def find_submitted_reviews_by_reviewer_group(
    reviewer_group_id: str,
    *,
    since,
) -> List[dict]:
    filters: Dict[str, Any] = {"created_at": {"$gte": since}}
    filters.update(_review_participant_filter("reviewer_group_id", reviewer_group_id))
    return list(
        db[REVIEWS_COLLECTION]
        .find(
            filters,
            {
                "transaction_id": 1,
                "transaction_type": 1,
                "score": 1,
                "reviewer_role": 1,
                "status": 1,
                "created_at": 1,
            },
        )
        .sort("created_at", -1)
    )
