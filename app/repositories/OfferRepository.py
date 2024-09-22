from app.config import database
from app.schemas.Offer import Offer
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

def insert(payload: Offer):
    offer_payload = {
        **payload.dict(),
        "status": payload.status.value,
        "type": payload.type
    }
    print(offer_payload)
    return database.db["Offers"].insert_one(offer_payload)


def find(filters):
    return database.db["Offers"].find(filters)


def find_by_request_id_and_group(request_id: str, group_id: str):

    filters = {
        "request_id": request_id
    }

    if group_id != None:
        filters["group_id"] = group_id

    return database.db["Offers"].aggregate([
        {
            "$match": filters
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
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"group_id": {"$toObjectId": "$group_id"}},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$_id", "$$group_id"]}
                        }
                    }
                ],
                "as": "group_info"
            }
        },
        {
            "$unwind": {
                "path": "$group_info",
                "preserveNullAndEmptyArrays": True
            }
        }
    ])


def find_by_request_ids(request_ids, group_id):
    filters = {
        "request_id": {"$in": request_ids}
    }

    if group_id is not None and len(group_id) > 0:
        filters["group_id"] = group_id

    return database.db["Offers"].find(filters)


def build_filter(propName):
    return database.db["Offers"].distinct(propName)


def edit_offer(offer_uid: str, payload: Offer):
    offer_id = ObjectId(offer_uid)
    offer_data = payload.dict()

    if 'status' in offer_data:
        offer_data['status'] = offer_data['status'].value
    if 'type' in offer_data:
        offer_data['type'] = offer_data['type'].value

    offer_data.pop('id', None)

    return database.db["Offers"].find_one_and_update({"_id": offer_id}, {"$set": offer_data}, return_document=ReturnDocument.AFTER)


def find_offer_by_id(offer_uid: str):
    offer_id = ObjectId(offer_uid)
    return database.db["Offers"].find_one({"_id": offer_id})
