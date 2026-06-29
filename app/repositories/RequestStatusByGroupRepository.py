from app.config import database
from app.schemas.RequestStatusByGroup import RequestStatusByGroup
from pymongo.errors import PyMongoError
from pymongo import ReturnDocument
from bson import ObjectId

db = database.db["RequestStatusByGroup"]


def insert(payload: RequestStatusByGroup) -> RequestStatusByGroup:
    try:   
        insert_obj = payload.toJson()
        insert_obj.pop('_id')
    
        inserted_id = db.insert_one(insert_obj).inserted_id
        payload.id = str(inserted_id)
        return payload
    except PyMongoError as e:
        raise PyMongoError(f"Error while inserting request status by group: {str(e)}")


def find_by_group_and_request_id(group_id: str, request_id: str) -> RequestStatusByGroup | None:
    try:
        found_doc = db.find_one({"group_id": group_id, "request_id": request_id})

        if found_doc != None:
            request_status = RequestStatusByGroup(**found_doc)
            return request_status

        return None
    except PyMongoError as e:
        raise PyMongoError(f"Error while finding request status by group_id={group_id} and request_id={request_id}: {str(e)}")


def update(id: str, payload: RequestStatusByGroup) -> RequestStatusByGroup | None:
    try:
        request_status_id = ObjectId(id)
        payload_json = payload.toJson()
        payload_json.pop("_id", None)

        updated_doc = db.find_one_and_update(
            {"_id": request_status_id},
            {"$set": payload_json},
            return_document=ReturnDocument.AFTER
        )

        if updated_doc is not None:
            return RequestStatusByGroup(**updated_doc)

        return None
    except PyMongoError as e:
        raise PyMongoError(f"Error while updating request status by group id={id}: {str(e)}")


def delete(id: str) -> bool:
    try:
        result = db.delete_one({"_id": ObjectId(id)})
        return result.deleted_count == 1
    except PyMongoError as e:
        raise PyMongoError(f"Error while deleting request status {id}")
