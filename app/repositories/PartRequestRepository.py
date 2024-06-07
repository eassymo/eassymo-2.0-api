from app.config import database
from bson import ObjectId


def insert(part_request):
    return database.db["PartRequests"].insert_one(part_request)


def find_by_group_and_user(user_uid, group_uid):
    return database.db["PartRequests"].find(
        {
            "$or": [
                {"creatorUser": user_uid},
                {"subscribedSellers": group_uid}
            ]
        }
    )
