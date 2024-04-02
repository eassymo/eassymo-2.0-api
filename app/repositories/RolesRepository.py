from app.config import database

def find():
    return database.db["Roles"].find({})