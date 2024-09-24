from app.config import database
from bson import ObjectId
import pymongo


def insert(data):
    return database.db["Census"].insert_one(data)


def find(filters, limit=20, skip=0):
    try:
        census_filters = {
            **filters,
            "Entity_Visible": "Y",
            "Entity_Active": "Y"
        }

        if "show_only_census" in filters and filters["show_only_census"] is not None:
            census_filters["group_reference_id"] = {"$exists": False}

        print(census_filters)
        census_filters.pop("limit", None)
        census_filters.pop("page", None)
        census_filters.pop("show_only_census", None)

        skip = limit * (skip - 1)
        return database.db["Census"].find(census_filters).limit(limit).skip(skip).sort([
            ('Entity_Name', pymongo.ASCENDING)
        ])
    except Exception as e:
        print(f"An error occurred in find(): {str(e)}")
        # You might want to log the error or handle it in a specific way
        raise  # Re-raise the exception after logging


def count(filters):
    census_filters = {
        **filters,
        "Entity_Visible": "Y",
        "Entity_Active": "Y"
    }

    census_filters.pop("limit")
    census_filters.pop("page")

    total_count = database.db["Census"].count_documents(census_filters)
    group_count = database.db["Census"].count_documents(
        {**census_filters, "group_reference_id": {"$exists": True}})
    return {
        "total_count": total_count,
        "group_count": group_count
    }


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
