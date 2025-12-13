from app.config import database
from app.schemas.OfferStatusByGroup import OfferStatusByGroup
from pymongo.errors import PyMongoError
from pymongo import ReturnDocument
from bson import ObjectId

db = database.db["OfferStatusByGroup"]


def insert(payload: OfferStatusByGroup) -> OfferStatusByGroup:
    try:
        inserted_id = db.insert_one(payload.toJson()).inserted_id
        payload.id = str(inserted_id)
        return payload
    except PyMongoError as e:
        raise PyMongoError(f"Error while inserting offer status by group: {str(e)}")


def find_by_group_and_offer_id(group_id: str, offer_id: str) -> OfferStatusByGroup | None:
    try:
        found_doc = db.find_one({"group_id": group_id, "offer_id": offer_id})

        if found_doc != None:
            offer_status = OfferStatusByGroup(**found_doc)
            return offer_status

        return None
    except PyMongoError as e:
        raise PyMongoError(f"Error while finding offer status by group_id={group_id} and offer_id={offer_id}: {str(e)}")


def update(id: str, payload: OfferStatusByGroup) -> OfferStatusByGroup | None:
    try:
        offer_status_id = ObjectId(id)
        payload_json = payload.toJson()
        payload_json.pop("_id", None)

        updated_doc = db.find_one_and_update(
            {"_id": offer_status_id},
            {"$set": payload_json},
            return_document=ReturnDocument.AFTER
        )

        if updated_doc is not None:
            return OfferStatusByGroup(**updated_doc)

        return None
    except PyMongoError as e:
        raise PyMongoError(f"Error while updating offer status by group id={id}: {str(e)}")
