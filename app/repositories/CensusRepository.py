from app.config import database
from bson import ObjectId
import pymongo


def insert(data):
    return database.db["Census"].insert_one(data)


def find(filters):
    census_filters = {
        **filters,
        "Entity_Visible": "Y",
        "Entity_Active": "Y"
    }
    return database.db["Census"].find(census_filters).limit(20).sort('Entity_Name', pymongo.ASCENDING)


def find_by_id(id):
    mongo_id = ObjectId(id)
    return database.db["Census"].find_one({"_id": mongo_id})


def update(id, body):
    mongo_id = ObjectId(id)
    return database.db["Census"].update_one({"_id": mongo_id}, {"$set": body})


def find_states():
    return database.db["Census"].distinct('Entity_Location_State')


def find_city(state: str):
    return database.db["Census"].distinct("Entity_Address_City", {"Entity_Location_State": state})
