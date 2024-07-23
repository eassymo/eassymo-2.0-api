from app.config import database
from bson import ObjectId


def insert(part_request):
    return database.db["PartRequests"].insert_one(part_request)


def find_by_group_and_user(user_uid, group_uid):
    return database.db["PartRequests"].find(
        {
            "$or": [
                {"creatorUser": user_uid},
                {"subscribedSellers": group_uid}
            ]
        }
    )


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
    ])


def search_reduced(filters):
    return database.db["PartRequests"].find({**filters, "isActive": True}, {"part": 1, "vehicleInformation": 1, "createdAt": 1, "_id": 1})
