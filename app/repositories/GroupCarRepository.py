from app.config import database
from bson import ObjectId


def insert(groupCar):
    return database.db["GroupCars"].insert_one(groupCar)


def find_by_group(group_id: str):
    return database.db["GroupCars"].find({"group": group_id})


def find_by_id(id: str):
    car_id = ObjectId(id)
    return database.db["GroupCars"].find_one({"_id": car_id})
