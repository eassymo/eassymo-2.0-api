from app.config import database
from app.schemas.Offer import Offer
from bson import ObjectId


def insert(payload: Offer):
    offer_payload = {
        **payload.model_dump(),
        "status": payload.status,
        "type": payload.type
    }
    return database.db["Offers"].insert_one(offer_payload)


def find(filters):
    return database.db["Offers"].find(filters)


def find_by_request_id_and_group(request_id: str, group_id: str):
    return database.db["Offers"].find({"request_id": request_id, "group_id": group_id})


def find_by_request_ids(request_ids):
    return database.db["Offers"].find({
        "request_id": {"$in": request_ids}
    })


def build_filter(propName):
    return database.db["Offers"].distinct(propName)
