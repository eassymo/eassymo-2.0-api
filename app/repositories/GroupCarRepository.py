from app.config import database
from bson import ObjectId


def insert(groupCar):
    return database.db["GroupCars"].insert_one(groupCar)


def find_by_group(group_id: str):
    return database.db["GroupCars"].find({"group": group_id, "active": True})


def find_by_id(id: str):
    car_id = ObjectId(id)
    return database.db["GroupCars"].find_one({"_id": car_id})


def edit(id: ObjectId, payload):
    return database.db["GroupCars"].update_one({"_id": id}, {"$set": {**payload}})


def soft_remove(id: ObjectId):
    return database.db["GroupCars"].update_one({"_id": id}, {"$set": {"active": False}})
