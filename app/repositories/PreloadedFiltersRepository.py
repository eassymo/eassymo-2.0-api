from app.config import database
from app.schemas.PreloadedFilters import PreloadedFiltersTypes, PreloadedFilters
from bson import ObjectId
from pymongo import ReturnDocument


def find_by_user_group_type(user_uid: str, group_id: str, type: PreloadedFiltersTypes):
    return database.db["PreloadedFilters"].find({"user_uid": user_uid, "group_id": group_id, "type": type.value})


def create(payload: PreloadedFilters) -> PreloadedFilters:
    payload_json = payload.toJson()
    payload_json.pop("_id")
    inserted_id = database.db["PreloadedFilters"].insert_one(
        payload_json).inserted_id
    payload.id = inserted_id
    return payload


def update(id: str, payload: PreloadedFilters) -> PreloadedFilters:
    filter_id = ObjectId(id)
    payload_json = payload.toJson()
    payload_json.pop("_id", None)

    updated_filter = database.db["PreloadedFilters"].find_one_and_update(
        {"_id": filter_id},
        {"$set": payload_json},
        return_document=ReturnDocument.AFTER
    )

    if updated_filter:
        return PreloadedFilters(**updated_filter)
    return None


def delete(id: str) -> bool:
    id = ObjectId(id)

    deleted_filter = database.db["PreloadedFilters"].delete_one({"_id": id})

    return deleted_filter.deleted_count > 0
