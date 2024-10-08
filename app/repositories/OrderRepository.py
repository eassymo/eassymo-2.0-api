from app.config import database
from bson import ObjectId
from app.schemas import Order
import pymongo


def insert(order: dict):
    return database.db["Orders"].insert_one(order)


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
        }, {
            "$unwind": {
                "path": "$request_group",
                "preserveNullAndEmptyArrays": True
            }
        },
    ])
