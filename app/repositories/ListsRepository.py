from app.config import database
from bson import ObjectId


def insert(data):
    return database.db["Lists"].insert_one(data)


def find_by_user(uid: str):
    return database.db["Lists"].find({"user_uid": uid})


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
