from app.repositories import ListsRepository as listsRepository
from app.schemas.Lists import ListsSchema
from pymongo.errors import PyMongoError
from app.exceptions.InternalServerError import InternalServerError
from typing import Dict, Any
from bson import ObjectId


def create_list(data: ListsSchema):
    list_info = {
        **data.dict()
    }
    try:
        user_lists = list(listsRepository.find(
            {"user_uid": data.user_uid, "group_id": data.group_id}))
        if user_lists is not None and len(user_lists) > 0:
            list_id = user_lists[0]["_id"]
            listsRepository.insert_group_to_list(list_id, data.groups[0])
            return {"body": str(list_id)}
        created_list = listsRepository.insert(list_info)
        return {"body": str(created_list.inserted_id)}
    except PyMongoError as error:
        raise InternalServerError(str(error))


def get_lists_by_user_and_group(user_uid: str, group_id: str):
    try:
        filters = {"user_uid": user_uid, "group_id": group_id}
        user_lists = list(
            listsRepository.find_by_user_and_group(filters))
        user_lists = [ListsSchema(**list_data).toJson()
                      for list_data in user_lists]
        return {"body": user_lists}
    except PyMongoError as error:
        raise InternalServerError(str(error))


def update(user_info: Dict[str, Any], list_id: str, payload: ListsSchema):
    try:
        json_payload = payload.toJson()

        if payload.groups_info != None and len(payload.groups_info) > 0:
            json_payload.pop('groups_info')

        json_payload.pop('_id')
        listsRepository.update(list_id, json_payload)

        filters = {"_id": ObjectId(list_id)}

        found_lists = list(listsRepository.find_by_user_and_group(filters))
        updated_list: ListsSchema
        if len(found_lists) > 0:
            updated_list = ListsSchema(**found_lists[0])

        return updated_list.toJson()
    except PyMongoError as error:
        raise InternalServerError(str(error))
