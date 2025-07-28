from app.config import database
from typing import List, Dict, Any
from bson import ObjectId
from pymongo.results import UpdateResult
from typing import Optional


def insert(groupData):
    return database.db["groups"].insert_one(groupData)


def find(filters: Dict[str, Any], projection: Optional[Dict[str, Any]] = {}):
    return database.db["groups"].find(filters, projection)


def find_by_id(id: str, projection: Dict[str, Any] = None):
    mongo_id = ObjectId(id)
    return database.db["groups"].find_one({"_id": mongo_id}, projection)


def find_by_user(uid: str):
    return database.db["groups"].find({"users": uid})


def find_by_id_list(ids: List[ObjectId]):
    return database.db["groups"].find({"_id": {"$in": ids}})


def find_within_radius(group_ids: List[str], center_location: Dict[str, Any], radius_meters: int = 500):
    """Find groups within a specific radius of a center location"""
    object_ids = [ObjectId(group_id) for group_id in group_ids]
    
    return database.db["groups"].find({
        "_id": {"$in": object_ids},
        "location": {
            "$near": {
                "$geometry": center_location,
                "$maxDistance": radius_meters
            }
        }
    })


def distinct_by_id():
    group_ids = list(database.db["groups"].distinct("_id"))

    return database.db["groups"].aggregate([
        {"$match": {"_id": {"$in": group_ids}}},
        {"$project": {"_id": {"$toString": "$_id"}, "name": 1}}
    ])


def find_users_by_group_id(group_id: str):
    group_id = ObjectId(group_id)
    return database.db["groups"].find_one({"_id": group_id}, {"users": 1})


def edit_group(group_id: str, payload: Dict[str, Any]) -> UpdateResult:
    group_id = ObjectId(group_id)
    return database.db["groups"].find_one_and_update(
        {"_id": group_id}, 
        {"$set": {**payload}},
        return_document=True
    )
