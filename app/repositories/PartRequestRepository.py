from pymongo.errors import PyMongoError
from app.config import database
from bson import ObjectId
from pymongo import ReturnDocument
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from app.schemas.PartRequest import PartRequest, PartRequestStatus


def insert(part_request):
    return database.db["PartRequests"].insert_one(part_request)


def delete_by_ids(ids: List[ObjectId]) -> None:
    """Roll back docs inserted earlier in a batch that failed before anyone was notified."""
    if ids:
        database.db["PartRequests"].delete_many({"_id": {"$in": list(ids)}})


def find_by_id(id) -> Optional[dict]:
    try:
        return database.db["PartRequests"].find_one({"_id": ObjectId(id)})
    except Exception:
        return None


def find_by_specific_order_uid(specific_order_uid: str):
    return database.db["PartRequests"].find({"specific_order_uid": specific_order_uid})


def find(filters, projection):
    return database.db["PartRequests"].find(filters, projection or None).sort({"_id": -1})


def find_for_call_center(filters):
    return database.db["PartRequests"].aggregate([
        {
            "$match": filters
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"creatorGroupId": {"$toObjectId": "$creatorGroup"}},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$_id", "$$creatorGroupId"]}
                        }
                    }
                ],
                "as": "group_info"
            }
        },
        {
            "$unwind": {
                "path": "$group_info",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$sort": {
                "_id": -1
            }
        }
    ])


def find_one_by_id(id: str):
    return database.db["PartRequests"].find_one({"_id": ObjectId(id)})


def find_by_id(id: str):
    return database.db["PartRequests"].aggregate([
        {
            "$match": {"_id": ObjectId(id)}
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"creatorGroupId": {"$toObjectId": "$creatorGroup"}},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$_id", "$$creatorGroupId"]}
                        }
                    }
                ],
                "as": "group_info"
            }
        },
        {
            "$unwind": {
                "path": "$group_info",
                "preserveNullAndEmptyArrays": True
            }
        }
    ])


def find_sister_part_requests(specific_order_uid: str, status: Optional[str]):

    # A part the buyer removed keeps its status, so it is left out by its `removed` record.
    filters = {"specific_order_uid": specific_order_uid}

    if status != None:
        filters["status"] = status
    filters["removed"] = {"$exists": False}

    return database.db["PartRequests"].find(filters, {"part": 1, "_id": 1})


def find_grouped(filters, skip: int = 0, limit: int = 10):
    return database.db["PartRequests"].aggregate([
        {
            "$match": filters
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"group_id": {"$toObjectId": "$creatorGroup"}},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$_id", "$$group_id"]}
                        }
                    }
                ],
                "as": "group_info"
            }
        },
        {
            "$unwind": {
                "path": "$group_info",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$sort": {
                "createdAt": -1
            }
        },
        {
            "$skip": skip
        },
        {
            "$limit": limit
        }
    ])


def count_grouped(filters):
    return database.db["PartRequests"].count_documents(filters)


def find_open_ids(filters):
    """Just the _id of each matching request (used to bound the offers lookup)."""
    return [doc["_id"] for doc in database.db["PartRequests"].find(filters, {"_id": 1})]


def _unquoted_match(filters, excluded_ids):
    return {"$and": [filters, {"_id": {"$nin": list(excluded_ids)}}]} if excluded_ids else filters


def find_unquoted(filters, excluded_ids, limit: int = 200):
    """Newest first, with the buyer's group as group_info (same lookup as find_grouped)."""
    return database.db["PartRequests"].aggregate([
        {"$match": _unquoted_match(filters, excluded_ids)},
        {"$sort": {"createdAt": -1}},
        {"$limit": limit},
        {
            "$lookup": {
                "from": "groups",
                "let": {"group_id": {"$toObjectId": "$creatorGroup"}},
                "pipeline": [{"$match": {"$expr": {"$eq": ["$_id", "$$group_id"]}}}],
                "as": "group_info",
            }
        },
        {"$unwind": {"path": "$group_info", "preserveNullAndEmptyArrays": True}},
    ])


def count_unquoted(filters, excluded_ids):
    return database.db["PartRequests"].count_documents(_unquoted_match(filters, excluded_ids))


def distinct_vehicle_ids_grouped(filters: Dict[str, Any]) -> List[Any]:
    """Distinct vehicleId values for documents matching the same filter as find_grouped $match."""
    return database.db["PartRequests"].distinct("vehicleId", filters)

def search_reduced(filters):

    aggregation = [
        {
            "$match": filters
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"creatorGroupId": {"$toObjectId": "$creatorGroup"}},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$_id", "$$creatorGroupId"]}
                        }
                    }
                ],
                "as": "group_info"
            }
        },
        {
            "$unwind": {
                "path": "$group_info",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$project": {
                "_id": 1,
                "part": 1,
                "vehicleInformation": 1,
                "createdAt": 1,
                "group_info": 1,
            }
        }
    ]

    return database.db["PartRequests"].aggregate(aggregation)


def build_filter(propName):
    return database.db["PartRequests"].distinct(propName)


def distinct_by_vehicle():
    return database.db["PartRequests"].aggregate([
        {
            "$group": {
                "_id": "$vehicleInformation.model",
                "subModel": {"$first": "$vehicleInformation.subModel"},
                "maker": {"$first": "$vehicleInformation.maker"},
                "year": {"$first": "$vehicleInformation.year"},
                "engine": {"$first": "$vehicleInformation.engine"},
            }
        },
        {
            "$project": {
                "name": {
                    "$concat": [
                        {"$ifNull": ["$maker", ""]},
                        " ",
                        "$_id",
                        " ",
                        {"$ifNull": ["$subModel", ""]},
                        " ",
                        {"$ifNull": ["$year", ""]},
                        " ",
                        {"$ifNull": ["$engine", ""]}
                    ]
                }
            }
        }
    ])


def edit_part_request(id: str, data, push: Optional[dict] = None):
    """`$set` the data; `push` appends to arrays in the same write (e.g. {"change_log": change})."""
    part_request_id = ObjectId(id)
    update = {"$set": {**data}}
    if push:
        update["$push"] = push
    updated_part_request = database.db["PartRequests"].find_one_and_update(
        {"_id": part_request_id}, update, return_document=ReturnDocument.AFTER)
    return updated_part_request


def claim_removal(id: str, uid: str, at: datetime, stale_before: datetime) -> bool:
    """Mark the part as being removed by `uid`, only if no one removed it or is removing it now. A claim older than
    `stale_before` (its request died midway) can be taken over."""
    claimed = database.db["PartRequests"].find_one_and_update(
        {
            "_id": ObjectId(id),
            "removed": {"$exists": False},
            "$or": [{"removing": {"$exists": False}}, {"removing.at": {"$lt": stale_before}}],
        },
        {"$set": {"removing": {"by": uid, "at": at}}},
    )
    return claimed is not None


def release_removal(id: str, uid: str, at: datetime) -> None:
    """Drop this request's claim after a failed removal, so a retry can run at once."""
    database.db["PartRequests"].update_one(
        {"_id": ObjectId(id), "removing.by": uid, "removing.at": at}, {"$unset": {"removing": ""}})


def _request_filter(part: dict) -> Optional[dict]:
    """The parts of `part`'s request as the buyer's edit screen lists them: by order uid; a part without one, by parent
    uid among the parts without one. None when the part has neither (it is a request on its own). One parent batch may
    span several orders: each order is its own request."""
    if part.get("specific_order_uid"):
        return {"specific_order_uid": part["specific_order_uid"]}
    if part.get("parent_request_uid"):
        return {"parent_request_uid": part["parent_request_uid"], "specific_order_uid": {"$in": [None, ""]}}
    return None


def count_live_others(part: dict, stale_before: datetime) -> Tuple[int, int]:
    """(live, free): the other live parts of `part`'s request (any status, active, not removed), and how many of them
    no one is removing now (no claim, or one older than `stale_before`)."""
    request = _request_filter(part)
    if request is None:
        return 0, 0
    live = {"creatorGroup": part.get("creatorGroup"), **request, "_id": {"$ne": ObjectId(str(part["_id"]))},
            "isActive": {"$ne": False}, "removed": {"$exists": False}}
    collection = database.db["PartRequests"]
    live_count = collection.count_documents(live)
    if not live_count:
        return 0, 0
    free_count = collection.count_documents(
        {**live, "$or": [{"removing": {"$exists": False}}, {"removing.at": {"$lt": stale_before}}]})
    return live_count, free_count


def count(filters) -> int:
    return database.db["PartRequests"].count_documents(filters)


def distinct(property_name: str, filters: Dict[str, Any]):
    return database.db["PartRequests"].distinct(property_name, filters)


def _iso_text(value: datetime) -> str:
    """The text form JS and toJson() wrote: UTC, milliseconds, "Z" (sorts like the date it names)."""
    utc = value.astimezone(timezone.utc) if value.tzinfo else value
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


# createdAt as a date: a BSON date or ISO text (old writers). A text that is not a date becomes null instead of
# failing the whole aggregation.
_CREATED_AT = {"$convert": {"input": "$createdAt", "to": "date", "onError": None, "onNull": None}}

# A request without a parent uid is its own batch (by its order, else by itself), never one "" bucket.
_BATCH_KEY = {
    "$cond": [
        {"$gt": [{"$strLenCP": {"$ifNull": ["$parent_request_uid", ""]}}, 0]},
        "$parent_request_uid",
        {"$ifNull": ["$specific_order_uid", {"$toString": "$_id"}]},
    ]
}


def open_turn_days(seller_group_id: str, since: datetime, tz: str) -> List[dict]:
    """Open requests for a seller since `since`, as one row per (local day, batch) with that day's part ids.

    createdAt is a BSON date on most docs and ISO text on some: both are read through `_CREATED_AT`.
    """
    try:
        created = _CREATED_AT
        rows = database.db["PartRequests"].aggregate([
            {"$match": {
                "subscribedSellers": seller_group_id,
                "status": PartRequestStatus.CREATED.value,
                "$expr": {"$gte": [created, since]},
            }},
            {"$project": {
                "day": {"$dateToString": {"format": "%Y-%m-%d", "date": created, "timezone": tz}},
                "parent_request_uid": 1,
                "specific_order_uid": 1,
            }},
            {"$group": {"_id": {"day": "$day", "batch": _BATCH_KEY}, "part_ids": {"$push": "$_id"}}},
        ])
        return [{"day": row["_id"]["day"], "batch": row["_id"]["batch"], "part_ids": row["part_ids"]} for row in rows]
    except PyMongoError as e:
        raise PyMongoError(f"Error while finding open turn days for seller {seller_group_id}: {str(e)}")


def find_grouped_by_parent_request_uid(
    creator_group_id: Optional[str],
    seller_group_id: Optional[str],
    status: Optional[PartRequestStatus],
    specific_order_uid: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
):
    """Open batches ("turns"), oldest arrival first. `created_from`/`created_to` limit them to one day."""
    try:
        filters = {}

        if creator_group_id != None and len(creator_group_id.strip()) > 0:
            filters["creatorGroup"] = creator_group_id

        if seller_group_id != None and len(seller_group_id.strip()) > 0:
            filters["subscribedSellers"] = seller_group_id

        if specific_order_uid != None and len(specific_order_uid.strip()) > 0:
            filters["specific_order_uid"] = specific_order_uid

        if status != None:
            filters["status"] = status.value

        if created_from is not None or created_to is not None:
            # createdAt is a BSON date on most docs and ISO text on some (old writers): match the day in both.
            as_date, as_text = {}, {}
            if created_from is not None:
                as_date["$gte"] = created_from
                as_text["$gte"] = _iso_text(created_from)
            if created_to is not None:
                as_date["$lt"] = created_to
                as_text["$lt"] = _iso_text(created_to)
            filters["$or"] = [{"createdAt": as_date}, {"createdAt": as_text}]

        return database.db["PartRequests"].aggregate([
            {"$match": filters},
            {
                "$group": {
                    "_id": _BATCH_KEY,
                    "first_created": {"$min": _CREATED_AT},
                    "part_requests": {"$push": "$$ROOT"}
                }
            },
            {
                "$sort": {"first_created": 1, "_id": 1}
            }
        ])
    except PyMongoError as e:
        raise PyMongoError(f"Error while finding part requests grouped by parent_request_uid: {str(e)}")