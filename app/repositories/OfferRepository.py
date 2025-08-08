from app.config import database
from app.schemas.Offer import Offer
from typing import List, Dict, Any, Optional
from bson import ObjectId
from pymongo import ReturnDocument, ASCENDING, DESCENDING
from app.schemas.Offer import OfferStatus


def insert(payload: Dict[str, Any]):
    return database.db["Offers"].insert_one(payload)


def find(filters, projection={}):
    return database.db["Offers"].find(filters, projection)


def find_by_request_id_and_group(request_id: str, group_ids: List[str], is_callcenter=False):

    filters = {
        "request_id": request_id
    }

    if group_ids != None and len(group_ids) > 0:
        filters["group_id"] = {"$in": group_ids}

    if is_callcenter == True:
        filters.pop("group_id")
        filters["$or"] = [
            {"call_center_that_posted_offer._id":  group_ids[0]},
            {"group_id": {"$in": group_ids}}
        ]

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
                "createdAt": 1,
                "call_center_that_posted_offer": 1,
                "call_center_user_that_posted_offer": 1,
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


def find_by_request_ids(request_ids, group_id, additional_filters: None | Dict[str, any] = None):
    filters = {
        "request_id": {"$in": request_ids}
    }

    if additional_filters != None:
        filters = {**filters, **additional_filters}

    if group_id is not None and len(group_id) > 0:
        filters["group_id"] = group_id

    return database.db["Offers"].find(filters).sort("_id", DESCENDING)


def build_filter(propName):
    return database.db["Offers"].distinct(propName)


def edit_offer(offer_uid: str, offer_data: dict):
    offer_id = ObjectId(offer_uid)

    return database.db["Offers"].find_one_and_update({"_id": offer_id}, {"$set": offer_data}, return_document=ReturnDocument.AFTER)


def find_offer_by_id(offer_uid: str):
    offer_id = ObjectId(offer_uid)
    return database.db["Offers"].find_one({"_id": offer_id})


def find_with_part_request(filters):

    return database.db["Offers"].aggregate([
        {
            "$match": filters
        },
        {
            "$lookup": {
                "from": "PartRequests",
                "let": {"request_id", {"$toObjectId": "$request_id"}},
                "pipeline": [
                    {
                        "$match": {"$expr": {"$eq": ["$_id", "$$request_id"]}}
                    }
                ],
                "as": "part_request"
            }
        }
    ])


def get_ranked_offers(offer_ids: List[ObjectId], extra_status: Optional[List[Dict[str, Any]]] = None):

    status_list = [
        {"status": OfferStatus.created.value},
        {"status": OfferStatus.selected.value},
    ]

    if extra_status is not None:
        status_list.extend(extra_status)


    return database.db["Offers"].find(
        {
            "_id": {"$in": offer_ids},
            "$or": status_list
        }
    ).sort('price', ASCENDING)


def count(filters):
    return database.db["Offers"].count_documents(filters)


def distinct(prop_name: str, filters):
    return database.db["Offers"].distinct(prop_name, filters)