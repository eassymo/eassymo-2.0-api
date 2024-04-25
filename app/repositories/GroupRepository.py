from app.config import database
from bson import ObjectId


def insert(groupData):
    return database.db["groups"].insert_one(groupData)


def find_by_id(id):
    mongo_id = ObjectId(id)
    return database.db["groups"].find_one({"_id": mongo_id})


def find_by_user(uid: str):
    return database.db["groups"].find({ "users": uid })