from app.config import database
from bson import ObjectId

def insert(part_request):
    return database.db["PartRequests"].insert_one(part_request);