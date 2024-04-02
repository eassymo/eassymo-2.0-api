from app.config import database


def insert(data):
    return database.db["Invitations"].insert_one(data)


def find_user_invites(userId: str):
    return database.db["Invitations"].find({"user": userId})
