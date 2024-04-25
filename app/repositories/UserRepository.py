from app.config import database


def find_by_uid(uid: str):
    return database.db["Users"].find_one({"uid": uid})


def insert_user(user):
    return database.db["Users"].insert_one(user)


def update_user(uid: str, user):
    return database.db["Users"].update_one({"uid": uid}, {"$set": user})


def add_user_group(uid: str, group_id):
    return database.db["Users"].update_one({"uid": uid}, {"$addToSet": {"groups": group_id}})
