from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING, DESCENDING

from app.config import database

PERCEPTIONS_COLLECTION = "relationship_perceptions"
PREFS_COLLECTION = "relationship_reminder_prefs"

db = database.db


def ensure_indexes() -> None:
    perceptions = db[PERCEPTIONS_COLLECTION]
    perceptions.create_index(
        [
            ("reviewer_group_id", ASCENDING),
            ("direction", ASCENDING),
            ("counterpart_group_id", ASCENDING),
            ("created_at", DESCENDING),
        ],
        name="reviewer_direction_counterpart_created",
    )
    prefs = db[PREFS_COLLECTION]
    prefs.create_index([("uid", ASCENDING)], unique=True, name="uniq_reminder_uid")


def insert_perception(doc: dict):
    payload = dict(doc)
    payload.pop("_id", None)
    return db[PERCEPTIONS_COLLECTION].insert_one(payload)


def find_latest_perceptions(reviewer_group_id: str, direction: Optional[str] = None) -> List[dict]:
    match: Dict[str, Any] = {"reviewer_group_id": reviewer_group_id}
    if direction:
        match["direction"] = direction
    pipeline = [
        {"$match": match},
        {"$sort": {"created_at": -1}},
        {
            "$group": {
                "_id": {
                    "counterpart_group_id": "$counterpart_group_id",
                    "direction": "$direction",
                },
                "doc": {"$first": "$$ROOT"},
            }
        },
        {"$replaceRoot": {"newRoot": "$doc"}},
    ]
    return list(db[PERCEPTIONS_COLLECTION].aggregate(pipeline))


def find_latest_perception(
    reviewer_group_id: str,
    counterpart_group_id: str,
    direction: str,
) -> Optional[dict]:
    return db[PERCEPTIONS_COLLECTION].find_one(
        {
            "reviewer_group_id": reviewer_group_id,
            "counterpart_group_id": counterpart_group_id,
            "direction": direction,
        },
        sort=[("created_at", DESCENDING)],
    )


def find_prefs_by_uid(uid: str) -> Optional[dict]:
    return db[PREFS_COLLECTION].find_one({"uid": uid})


def upsert_prefs(uid: str, fields: Dict[str, Any]) -> dict:
    payload = dict(fields)
    payload["uid"] = uid
    db[PREFS_COLLECTION].update_one({"uid": uid}, {"$set": payload}, upsert=True)
    return find_prefs_by_uid(uid) or payload


def find_all_active_prefs() -> List[dict]:
    return list(db[PREFS_COLLECTION].find({"cadence": {"$ne": "off"}}))


def mark_prefs_sent(uid: str, sent_at: datetime) -> None:
    db[PREFS_COLLECTION].update_one(
        {"uid": uid},
        {"$set": {"last_sent_at": sent_at}},
    )


def claim_send_slot(uid: str, sent_at: datetime, window_start: datetime) -> bool:
    result = db[PREFS_COLLECTION].update_one(
        {
            "uid": uid,
            "$or": [
                {"last_sent_at": None},
                {"last_sent_at": {"$exists": False}},
                {"last_sent_at": {"$lt": window_start}},
            ],
        },
        {"$set": {"last_sent_at": sent_at}},
    )
    return result.modified_count > 0 or result.upserted_id is not None
