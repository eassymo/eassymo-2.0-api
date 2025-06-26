from app.config import database
from bson import ObjectId


def find(filters):
    return database.db["Roles"].find(filters)


def find_by_id(id: str):
    id = ObjectId(id)
    return database.db["Roles"].find_one({"_id": id})
