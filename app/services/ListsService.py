from app.repositories import ListsRepository as listsRepository
from app.repositories import GroupRepository as groupRepository
from app.schemas.Lists import ListsSchema
from app.schemas.Groups import GroupSchema
from pymongo.errors import PyMongoError
from app.exceptions.InternalServerError import InternalServerError
from typing import Dict, Any, List
from bson import ObjectId
from fastapi import HTTPException, status

from functools import wraps
import warnings


def deprecated(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        warnings.warn(f"The method {func.__name__} is deprecated and will be removed in a future version.",
                      DeprecationWarning, stacklevel=2)
        return func(*args, **kwargs)
    return wrapper


@deprecated
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


def insert_list(list: ListsSchema):
    try:
        if (check_if_name_is_repeated(list.name, list.user_uid, list.group_id)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="A list with that name already exists for this user")

        inserted_id = listsRepository.insert(list.toJson()).inserted_id

        return str(inserted_id)
    except PyMongoError as error:
        raise InternalServerError(str(error))


def check_if_name_is_repeated(name: str, user_uid: str, group_id: str) -> bool:
    results_found = list(listsRepository.find(
        {"name": name, "user_uid": user_uid, "group_id": group_id}))

    return len(results_found) > 0


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


def get_groups_from_lists(user_uid: str | None, group_id: str | None, exclude_lists: List[str]) -> List[GroupSchema]:
    try:
        if user_uid is None or group_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="User and group are required")

        filters: Dict[str, Any] = {
            "user_uid": user_uid,
            "group_id": group_id
        }

        if exclude_lists != None and len(exclude_lists) > 0:
            filters["_id"] = {
                "$nin": [ObjectId(list_id) for list_id in exclude_lists]}

        lists_found = list(listsRepository.find(filters))

        user_lists: List[ListsSchema] = []

        groups_list: List[GroupSchema] = []

        if len(lists_found) > 0:
            user_lists = [ListsSchema(**user_list)
                          for user_list in lists_found]

            accumulated_groups: List[ObjectId] = []
            for user_list in user_lists:
                accumulated_groups.extend(
                    [ObjectId(group_id) for group_id in user_list.groups])

        groups_list = _get_groups_info(accumulated_groups)

        return [group.toJson() for group in groups_list]
    except PyMongoError as error:
        raise InternalServerError(str(error))


def _get_groups_info(accumulated_groups: List[ObjectId]) -> List[GroupSchema]:
    try:
        groups_found = list(groupRepository.find(
            {"_id": {"$in": accumulated_groups}}))

        groups: List[GroupSchema] = []
        if len(groups_found) > 0:
            groups = [GroupSchema(**group) for group in groups_found]

        return groups
    except PyMongoError as error:
        raise InternalServerError(str(error))
