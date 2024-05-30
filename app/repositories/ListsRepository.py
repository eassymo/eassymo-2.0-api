from app.config import database
from bson import ObjectId


def insert(data):
    return database.db["Lists"].insert_one(data)


def find_by_user(uid: str):
    return database.db["Lists"].find({"user_uid": uid})


def find_lists_by_users_with_groups_info(uid: str):
    return database.db["Lists"].aggregate([
        {
            "$match": {"user_uid": uid}
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
    return database.db["Lists"].update_one({"_id": list_id}, {"$addToSet": {"groups": group_id}})


def find_all_groups_in_user_lists(user_uid: str):
    pipeline = [
        {"$match": {"user_uid": user_uid}},
        {"$unwind": "$groups"},
        {"$group": {
            "_id": None,
            "all_groups": {"$addToSet": "$groups"}
        }}
    ]

    return database.db["Lists"].aggregate(pipeline)
