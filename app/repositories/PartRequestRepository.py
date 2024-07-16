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
        {
            "$group": {
                "_id": {
                    "groupId": {"$toString": "$creatorGroup._id"},
                    "groupName": "$creatorGroup.name"
                },
                "totalRequests": {"$sum": 1},
                "partRequests": {"$push": {
                    "_id": { "$toString": "$_id" },
                    "creatorGroup": {
                        "_id": {"$toString": "$creatorGroup._id"},
                        "name": "$creatorGroup.name",
                        "type": "$creatorGroup.type",
                        "whatsAppNumber": "$creatorGroup.whatsAppNumber",
                        "state": "$creatorGroup.state",
                        "city": "$creatorGroup.city",
                        "country": "$creatorGroup.country",
                        "location": "$creatorGroup.location",
                        "phone": "$creatorGroup.phone",
                        "email": "$creatorGroup.email",
                        "webPage": "$creatorGroup.webPage",
                        "since": "$creatorGroup.since",
                        "story": "$creatorGroup.story",
                        "isActive": "$creatorGroup.isActive",
                        "address": "$creatorGroup.address",
                        "group_store_type": "$creatorGroup.group_store_type",
                        "users": "$creatorGroup.users",
                        "owner": "$creatorGroup.owner"
                    },
                    "creatorUser": "$creatorUser",
                    "vehicleId": "$vehicleId",
                    "vehicleInformation": {
                        "_id": {"$toString": "$vehicleInformation._id"},
                        "year": "$vehicleInformation.year",
                        "maker": "$vehicleInformation.maker",
                        "model": "$vehicleInformation.model",
                        "engine": "$vehicleInformation.engine",
                        "subModel": "$vehicleInformation.subModel",
                        "active": "$vehicleInformation.active",
                        "createdAt": "$vehicleInformation.createdAt"
                    },
                    "location": "$location",
                    "createdAt": {"$toString": "$createdAt"},
                    "photos": "$photos",
                    "updatedAt": {"$toString": "$updatedAt"},
                    "subscribedSellers": "$subscribedSellers",
                    "isActive": "$isActive",
                    "part": "$part",
                    "partList": "$partList"
                }}
            }
        },
        {
            "$sort": {"_id": -1}
        },
    ])
