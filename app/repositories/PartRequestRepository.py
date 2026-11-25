from pymongo.errors import PyMongoError
from app.config import database
from bson import ObjectId
from pymongo import ReturnDocument
from typing import Dict, Any, List, Optional

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

    filters = {"specific_order_uid": specific_order_uid}

    if status != None:
        filters["status"] = status
        
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


def edit_part_request(id: str, data):
    part_request_id = ObjectId(id)
    updated_part_request = database.db["PartRequests"].find_one_and_update(
        {"_id": part_request_id}, {"$set": {**data}}, return_document=ReturnDocument.AFTER)
    return updated_part_request


def count(filters) -> int:
    return database.db["PartRequests"].count_documents(filters)


def distinct(property_name: str, filters: Dict[str, Any]):
    return database.db["PartRequests"].distinct(property_name, filters)


def find_grouped_by_parent_request_uid(
    creator_group_id: Optional[str],
    seller_group_id: Optional[str],
    status: Optional[PartRequestStatus],
    specific_order_uid: Optional[str] = None,
):
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

        return database.db["PartRequests"].aggregate([
            {"$match": filters},
            {
                "$group": {
                    "_id": "$parent_request_uid",
                    "part_requests": {"$push": "$$ROOT"}
                }
            },
            {
                "$sort": {"_id": -1}
            }
        ])
    except PyMongoError as e:
        raise PyMongoError(f"Error while finding part requests grouped by parent_request_uid: {str(e)}")