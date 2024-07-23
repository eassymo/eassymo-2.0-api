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
    return database.db["Offers"].aggregate([
        {
            "$match": {"request_id": request_id, "group_id": group_id}
        },
        {
            "$lookup": {
                "from": "Users",
                "localField": "user_uid",
                "foreignField": "uid",
                "as": "user_info"
            }
        },
        {
            "$unwind": {
                "path": "$user_info",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$project": {
                "_id": 1,
                "request_id": 1,
                "user_uid": 1,
                "group_id": 1,
                "brand": 1,
                "guarantee": 1,
                "price": 1,
                "unit_of_measure": 1,
                "to_be_delivered_time": 1,
                "code": 1,
                "location": 1,
                "photos": 1,
                "internalComments": 1,
                "publicComments": 1,
                "status": 1,
                "type": 1,
                "user_info.uid": 1,
                "user_info.name": 1,
            }
        }
    ])


def find_by_request_ids(request_ids):
    return database.db["Offers"].find({
        "request_id": {"$in": request_ids}
    })


def build_filter(propName):
    return database.db["Offers"].distinct(propName)
