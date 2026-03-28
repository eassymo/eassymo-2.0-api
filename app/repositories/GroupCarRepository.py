from typing import List

from app.config import database
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import DESCENDING


def insert(groupCar):
    return database.db["GroupCars"].insert_one(groupCar)


def find(filters):
    return database.db["GroupCars"].find(filters)


def find_by_group(group_id: str):
    return database.db["GroupCars"].find({"group": group_id, "active": True}).sort("_id", DESCENDING)


def find_by_id(id: str):
    car_id = ObjectId(id)
    return database.db["GroupCars"].find_one({"_id": car_id})


def find_by_ids(ids: List[str]):
    object_ids = []
    for raw in ids:
        if not raw or not str(raw).strip():
            continue
        try:
            object_ids.append(ObjectId(str(raw).strip()))
        except InvalidId:
            continue
    if not object_ids:
        return []
    return list(database.db["GroupCars"].find({"_id": {"$in": object_ids}}))


def edit(id: ObjectId, payload):
    return database.db["GroupCars"].update_one({"_id": id}, {"$set": {**payload}})


def soft_remove(id: ObjectId):
    return database.db["GroupCars"].update_one({"_id": id}, {"$set": {"active": False}})
