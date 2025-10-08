from zoneinfo import ZoneInfo
from app.config import database
from bson import ObjectId
from app.schemas.Lists import ListsSchema
from pymongo.results import UpdateResult
from bson import ObjectId
from typing import Dict, Any
from datetime import datetime


def insert(data):
    return database.db["Lists"].insert_one(data)


def find_by_user_and_group(filters: Dict[str, Any]):
    return database.db["Lists"].aggregate([
        {
            "$match": filters
        },
        {
            "$addFields": {
                "groupIds": {
                    "$map": {
                        "input": "$groups",
                        "as": "group",
                        "in": {"$toObjectId": "$$group"}
                    }
                }
            }
        },
        {
            "$lookup": {
                "from": "groups",
                "localField": "groupIds",
                "foreignField": "_id",
                "as": "groups_info"
            }
        },
        {
            "$project": {
                "_id": 1,
                "name": 1,
                "user_uid": 1,
                "group_id": 1,
                "groups": 1,
                "is_priority": 1,
                "groups_info": 1,
                "is_favorite": 1
            }
        },
    ])


def find(filters):
    return database.db["Lists"].find(filters)


def find_lists_by_users_with_groups_info(uid: str, group_id: str):
    return database.db["Lists"].aggregate([
        {
            "$match": {"user_uid": uid, "group_id": group_id}
        },
        {
            "$addFields": {
                "groups": {
                    "$map": {
                        "input": "$groups",
                        "as": "group",
                        "in": {"$toObjectId": "$$group"}
                    }
                }
            }
        },
        {
            "$unwind": {
                "path": "$groups",
                "preserveNullAndEmptyArrays": True
            },
        },
        {
            "$lookup": {
                "from": "groups",
                "localField": "groups",
                "foreignField": "_id",
                "as": "group_info"
            }
        },
        {
            "$unwind": "$group_info"
        },
        {
            "$group": {
                "_id": "$_id",
                "name": {"$first": "$name"},
                "user_uid": {"$first": "$user_uid"},
                "groups": {"$push": "$group_info"}
            }
        }
    ])


def insert_group_to_list(list_id: str, group_id: str):
    return database.db["Lists"].update_one({"_id": ObjectId(list_id)}, {"$addToSet": {"groups": group_id}})


def find_all_groups_in_user_lists(user_uid: str | None, group_id: str):

    filters = {"group_id": group_id}

    if user_uid != None:
        filters = {**filters, "user_uid": user_uid}

    pipeline = [
        {"$match": filters},
        {"$unwind": "$groups"},
        {"$group": {
            "_id": None,
            "all_groups": {"$addToSet": "$groups"}
        }}
    ]

    return database.db["Lists"].aggregate(pipeline)


def update(list_id: str, payload: Dict[str, Any]) -> UpdateResult:
    id = ObjectId(list_id)

    utc_date = datetime.now(ZoneInfo('UTC'))
    payload["last_modified"] = utc_date
    return database.db["Lists"].find_one_and_update({"_id": id}, {"$set": payload}, return_document=True)
