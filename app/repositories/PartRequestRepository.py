from app.config import database
from bson import ObjectId
from app.schemas.PartRequest import PartRequest
from pymongo import ReturnDocument
from typing import List


def insert(part_request):
    return database.db["PartRequests"].insert_one(part_request)


def find(filters, projection):
    return database.db["PartRequests"].find(filters, projection)


def find_by_group_and_user(user_uid, group_uid):
    return database.db["PartRequests"].find(
        {
            "$or": [
                {"creatorUser": user_uid},
                {"subscribedSellers": group_uid}
            ]
        }
    )


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


def find_sister_part_requests(parent_request_id: str):
    return database.db["PartRequests"].find({"parent_request_uid": parent_request_id}, {"part": 1, "_id": 1})


def find_grouped(filters):
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
                "as": "creatorGroup"
            }
        },
        {
            "$unwind": {
                "path": "$creatorGroup",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$sort": {
                "createdAt": -1
            }
        }
    ])


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
