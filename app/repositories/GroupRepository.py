from app.config import database
from typing import List
from bson import ObjectId


def insert(groupData):
    return database.db["groups"].insert_one(groupData)


def find_by_id(id):
    mongo_id = ObjectId(id)
    return database.db["groups"].find_one({"_id": mongo_id})


def find_by_user(uid: str):
    return database.db["groups"].find({"users": uid})


def find_by_id_list(ids: List[ObjectId]):
    return database.db["groups"].find({"_id": {"$in": ids}})


def distinct_by_id():
    group_ids = list(database.db["groups"].distinct("_id"))

    return database.db["groups"].aggregate([
        {"$match": {"_id": {"$in": group_ids}}},
        {"$project": {"_id": {"$toString": "$_id"}, "name": 1}}
    ])

def find_users_by_group_id(group_id: str):
    group_id = ObjectId(group_id)
    return database.db["groups"].find_one({"_id": group_id}, {"users": 1})