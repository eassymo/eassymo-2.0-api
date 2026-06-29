from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from app.config import database
from bson import ObjectId


def _updated_at_completion_match_expr(start_utc: datetime, end_utc: datetime) -> Dict[str, Any]:
    """
    Orders usually store updated_at as a string (Order.toJson uses str(datetime)).
    Comparing that field to BSON dates in a plain $match never matches; parse in $expr instead.
    Handles updated_at stored as date or as Python's default str (space between date and time).
    """
    return {
        "$expr": {
            "$let": {
                "vars": {
                    "parsed": {
                        "$switch": {
                            "branches": [
                                {
                                    "case": {"$eq": [{"$type": "$updated_at"}, "date"]},
                                    "then": "$updated_at",
                                },
                            ],
                            "default": {
                                "$dateFromString": {
                                    "dateString": {
                                        "$replaceOne": {
                                            "input": {"$toString": "$updated_at"},
                                            "find": " ",
                                            "replacement": "T",
                                        }
                                    },
                                    "onError": None,
                                    "onNull": None,
                                }
                            },
                        }
                    }
                },
                "in": {
                    "$and": [
                        {"$ne": ["$$parsed", None]},
                        {"$gte": ["$$parsed", start_utc]},
                        {"$lte": ["$$parsed", end_utc]},
                    ]
                },
            }
        }
    }


def insert(order: dict):
    return database.db["Orders"].insert_one(order)


def find_by_id(id: ObjectId):
    return database.db["Orders"].aggregate([
        {
            "$match": {"_id": id}
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"group_id": "$offer.group_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$eq": ["$_id", {"$toObjectId": "$$group_id"}]
                            }
                        }
                    }
                ],
                "as": "offer_group"
            }
        },
        {
            "$unwind": {
                "path": "$offer_group",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"creator_group": "$part_request.creatorGroup"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$eq": ["$_id", {"$toObjectId": "$$creator_group"}]
                            }
                        }
                    }
                ],
                "as": "request_group"
            }
        },
        {
            "$unwind": {
                "path": "$request_group",
                "preserveNullAndEmptyArrays": True
            }
        },
    ])


def find(
    filters: Dict[str, Any],
    updated_at_completion_bounds: Optional[Tuple[datetime, datetime]] = None,
):
    match_stage = dict(filters)
    if updated_at_completion_bounds:
        start_utc, end_utc = updated_at_completion_bounds
        if "$expr" in match_stage:
            raise ValueError("filters cannot contain $expr when using updated_at_completion_bounds")
        match_stage.update(_updated_at_completion_match_expr(start_utc, end_utc))

    return database.db["Orders"].aggregate([
        {
            "$match": match_stage
        },
        {
            "$lookup": {
                "from": "users",
                "localField": "creator_user",
                "foreignField": "uid",
                "as": "user"
            }
        },
        {
            "$unwind": {
                "path": "$user",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"group_id": "$offer.group_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$eq": ["$_id", {"$toObjectId": "$$group_id"}]
                            }
                        }
                    }
                ],
                "as": "offer_group"
            }
        },
        {
            "$unwind": {
                "path": "$offer_group",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"creator_group": "$part_request.creatorGroup"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$eq": ["$_id", {"$toObjectId": "$$creator_group"}]
                            }
                        }
                    }
                ],
                "as": "request_group"
            }
        },
        {
            "$unwind": {
                "path": "$request_group",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$sort": {"created_at": -1}
        }
    ])


def find_one(filters):
    return database.db["Orders"].find_one(filters)


def edit(id: ObjectId, new_data):
    return database.db["Orders"].find_one_and_update(
        {"_id": id},
        {"$set": new_data},
        return_document=True
    )
