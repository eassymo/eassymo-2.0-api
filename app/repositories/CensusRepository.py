from app.config import database

import pymongo

def find(filters):
    return database.db["Census"].find(filters).limit(100).sort('Entity_Name', pymongo.ASCENDING)

def find_states():
    return database.db["Census"].distinct('Entity_Location_State')

def find_city(state: str):
    return database.db["Census"].distinct("Entity_Address_City", {"Entity_Location_State": state})