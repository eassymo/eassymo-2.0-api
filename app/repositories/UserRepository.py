from app.config import database
from typing import Dict, Any, Optional

def find_one(filters: Dict[str, Any]):
    return database.db["Users"].find_one(filters)


def find(filters: Dict[str, Any], limit: Optional[int] = 30):
    return database.db["Users"].find(filters).limit(limit)

def find_by_uid(uid: str):
    return database.db["Users"].aggregate([
        {
            "$match": {"uid": uid}
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"group_ids":  "$groups"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$in": ["$_id", {"$map": {
                                    "input": "$$group_ids",
                                    "as": "groupId",
                                    "in": {"$toObjectId": "$$groupId"}
                                }}]
                            }
                        }
                    }
                ],
                "as": "groups"
            }
        },
    ])


def insert_user(user):
    return database.db["Users"].insert_one(user)


def update_user(uid: str, user):
    return database.db["Users"].update_one({"uid": uid}, {"$set": user})


def add_user_group(uid: str, group_id):
    return database.db["Users"].update_one({"uid": uid}, {"$addToSet": {"groups": group_id}})
