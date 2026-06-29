from app.config import database
from bson import ObjectId
from typing import Dict, Any


def insert(payload: Dict[str, Any]):
    return database.db["PartRequestInvites"].insert_one(payload)


def find(filters: Dict[str, Any]):
    return database.db["PartRequestInvites"].find(filters)


def find_by_id(id: ObjectId):
    return database.db["PartRequestInvites"].find_one({"_id": id})


def find_one_and_update(id: ObjectId, data: Dict[str, Any]):
    return database.db["PartRequestInvites"].find_one_and_update({"_id": id}, {"$set": data}, return_document=True)
