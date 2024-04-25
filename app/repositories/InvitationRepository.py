from app.config import database
from bson import ObjectId


def insert(data):
    return database.db["Invitations"].insert_one(data)


def find_user_invites(userId: str):
    return database.db["Invitations"].find({"user": userId})


def find_by_id(id: str):
    mongo_id = ObjectId(id)
    return database.db["Invitations"].find_one({"_id": mongo_id})


def find_by_census_id(census_id: str):
    return database.db["Invitations"].find_one({"censusId": census_id})


def edit(id: str, data):
    mongo_id = ObjectId(id)
    return database.db["Invitations"].update_one({"_id": mongo_id}, {"$set": data})
