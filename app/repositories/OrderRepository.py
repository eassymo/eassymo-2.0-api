from app.config import database
from bson import ObjectId


def insert(order: dict):
    return database.db["Orders"].insert_one(order)


def find_by_id(id: ObjectId):
    return database.db["Orders"].find_one({"_id": id})


def find(filters):
    return database.db["Orders"].aggregate([
        {
            "$match": filters
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


def edit(id: ObjectId, new_data):
    return database.db["Orders"].find_one_and_update(
        {"_id": id},
        {"$set": new_data},
        return_document=True
    )
