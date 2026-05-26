from app.repositories import ListsRepository as listsRepository
from app.repositories import GroupRepository as groupRepository
from app.schemas.Lists import ListsSchema
from app.schemas.Groups import GroupSchema
from pymongo.errors import PyMongoError
from app.exceptions.InternalServerError import InternalServerError
from typing import Dict, Any, List
from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import DESCENDING

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

        group_info = groupRepository.find_by_id(data.groups[0])

        if group_info != None:
            group = GroupSchema(**group_info)
            user_lists = list(listsRepository.find(
                {"user_uid": data.user_uid, "group_id": data.group_id}))
            print(user_lists)
            if user_lists is not None and len(user_lists) > 0:
                if group.is_commissioner == False:
                    priority_lists = [
                        user_list for user_list in user_lists if user_list.get("is_priority") == True]
                    priority_list_id = str(priority_lists[0].get("_id"))
                    listsRepository.insert_group_to_list(
                        priority_list_id, data.groups[0])
                    return {"body": priority_list_id}
                else:
                    commissionable_list = [user_list for user_list in user_lists if user_list.get(
                        "name") == "Comisionables"]
                    if len(commissionable_list) > 0:
                        commissionable_list_id = str(
                            commissionable_list[0].get("_id"))
                        listsRepository.insert_group_to_list(
                            commissionable_list_id, data.groups[0])
                        return {"body": commissionable_list_id}
                    else:
                        commissionable_list_payload = {
                            **data.toJson(), "name": "Comisionables", "is_priority": False}
                        commissionable_list_payload.pop("_id")
                        created_list = listsRepository.insert(
                            commissionable_list_payload)
                        return {"body": str(created_list.inserted_id)}
            else:
                created_list = listsRepository.insert(list_info)
                return {"body": str(created_list.inserted_id)}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="")
    except PyMongoError as error:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Error while adding user to list")


def insert_list(list: ListsSchema):
    try:
        if list.name and list.name.strip() == "Comisionistas":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El nombre «Comisionistas» está reservado para la relación con comisionados",
            )
        if (check_if_name_is_repeated(list.name, list.user_uid, list.group_id)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="A list with that name already exists for this user")

        payload = list.toJson()

        payload.pop('_id')

        inserted_id = listsRepository.insert(payload).inserted_id

        return str(inserted_id)
    except PyMongoError as error:
        raise InternalServerError(str(error))




def add_comisionado_group_to_commissionables_list(inviting_user_uid: str, commissioner_group_id: str, invited_group_id: str) -> str:
    """Find or create the Comisionables list for invited_user scope and attach invited_group_id."""
    try:
        user_lists = list(
            listsRepository.find({"user_uid": inviting_user_uid, "group_id": commissioner_group_id})
        )
        commissionable_list = [u for u in user_lists if u.get("name") == "Comisionables"]

        if len(commissionable_list) > 0:
            cid = str(commissionable_list[0].get("_id"))
            listsRepository.insert_group_to_list(cid, invited_group_id)
            return cid

        commissionable_payload = {
            "user_uid": inviting_user_uid,
            "group_id": commissioner_group_id,
            "groups": [invited_group_id],
            "name": "Comisionables",
            "is_priority": False,
        }
        inserted = listsRepository.insert(commissionable_payload)
        return str(inserted.inserted_id)
    except PyMongoError as error:
        raise InternalServerError(str(error))


def add_commissioner_group_to_comisionistas_lists_for_invited_group(
    invited_group_id: str,
    commissioner_group_id: str,
    *,
    responding_user_uid: str | None = None,
) -> None:
    """Each user on the invited group gets a persisted «Comisionistas» list (commissioner group ids).

    responding_user_uid: user who accepted the invite — included even when Group.users is stale.
    """
    try:
        owner_uids_set: set[str] = set()
        if responding_user_uid and str(responding_user_uid).strip():
            owner_uids_set.add(str(responding_user_uid).strip())
        recipients = groupRepository.find_users_by_group_id(invited_group_id)
        for uid in (recipients or {}).get("users") or []:
            owner_id = uid
            if isinstance(uid, dict):
                owner_id = uid.get("_id") or uid.get("uid")
            if owner_id:
                owner_uids_set.add(str(owner_id).strip())

        if not owner_uids_set:
            return

        for owner_uid in owner_uids_set:
            if not owner_uid:
                continue
            user_lists = list(
                listsRepository.find({"user_uid": owner_uid, "group_id": invited_group_id}),
            )
            comisionistas_lists = [
                u for u in user_lists if u.get("name") == "Comisionistas"
            ]
            if len(comisionistas_lists) > 0:
                cid = str(comisionistas_lists[0].get("_id"))
                listsRepository.insert_group_to_list(cid, commissioner_group_id)
            else:
                payload = {
                    "user_uid": owner_uid,
                    "group_id": invited_group_id,
                    "groups": [commissioner_group_id],
                    "name": "Comisionistas",
                    "is_priority": False,
                    "is_favorite": False,
                }
                listsRepository.insert(payload)
    except PyMongoError as error:
        raise InternalServerError(str(error))


def check_if_name_is_repeated(name: str, user_uid: str, group_id: str) -> bool:
    results_found = list(listsRepository.find(
        {"name": name, "user_uid": user_uid, "group_id": group_id}))

    return len(results_found) > 0


def get_lists_by_user_and_group(user_uid: str | None, group_id: str):
    try:
        filters = {"group_id": group_id}

        if user_uid != None:
            filters = {**filters, "user_uid": user_uid}

        user_lists = list(
            listsRepository.find_by_user_and_group(filters))
        
        user_lists = [ListsSchema(**list_data).toJson()
                      for list_data in user_lists]
        return {"body": user_lists}
    except PyMongoError as error:
        raise InternalServerError(str(error))


def update(user_info: Dict[str, Any], list_id: str, payload: ListsSchema):
    try:
        old_docs = list(listsRepository.find({"_id": ObjectId(list_id)}))
        if len(old_docs) == 0:
            raise InternalServerError("Lista no encontrada")
        prev = old_docs[0]

        prev_name_raw = prev.get("name") or ""
        prev_name_norm = prev_name_raw.strip()
        incoming_name_norm = (payload.name or "").strip()

        if prev_name_norm == "Comisionistas":
            if incoming_name_norm != "Comisionistas":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No puedes renombrar la lista «Comisionistas».",
                )
            old_g = {str(x) for x in (prev.get("groups") or [])}
            new_g = {str(x) for x in (payload.groups or [])}
            removed = old_g - new_g
            if removed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Para quitar un comisionista usa «Quitar» en Mis listas; "
                        "así se corta la relación y también se actualiza el comisionado."
                    ),
                )
        elif incoming_name_norm == "Comisionistas":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El nombre «Comisionistas» está reservado para la relación con comisionados.",
            )

        json_payload = payload.toJson()

        if payload.groups_info != None and len(payload.groups_info) > 0:
            json_payload.pop('groups_info')

        json_payload.pop('_id')
        if prev_name_norm == "Comisionistas":
            json_payload["is_favorite"] = False
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


def get_groups_in_user_lists(
    user_uid: str,
    group_id: str,
    favorites_only: bool = False,
) -> List[str]:
    """Group ids appearing in the current user's lists for `group_id`."""
    try:
        filters: Dict[str, Any] = {
            "user_uid": user_uid,
            "group_id": group_id,
        }
        if favorites_only:
            filters["is_favorite"] = True

        lists_found = list(listsRepository.find(filters))
        group_ids: List[str] = []
        for user_list in lists_found:
            for group in user_list.get("groups", []):
                normalized = str(group) if group is not None else ""
                if normalized:
                    group_ids.append(normalized)
        return list(set(group_ids))
    except PyMongoError as error:
        raise InternalServerError(str(error))


def get_followers_not_in_my_lists(user_uid: str, group_id: str) -> List[str]:
    """
    Groups that have `group_id` in one of their lists, but the user has not
    added those groups to any of their own lists.
    """
    try:
        lists_containing_me = list(listsRepository.find({"groups": group_id}))
        owner_group_ids: List[str] = []
        for user_list in lists_containing_me:
            owner_id = user_list.get("group_id")
            if owner_id is not None:
                owner_group_ids.append(str(owner_id))

        owner_group_ids = list(set(owner_group_ids))
        my_list_group_ids = set(get_groups_in_user_lists(user_uid, group_id, favorites_only=False))
        return [gid for gid in owner_group_ids if gid not in my_list_group_ids]
    except PyMongoError as error:
        raise InternalServerError(str(error))


def get_followers_list(user_uid: str, group_id: str) -> List[Dict[str, Any]]:
    try:
        follower_group_ids = get_followers_not_in_my_lists(user_uid, group_id)

        if len(follower_group_ids) == 0:
            return []

        follower_group_ids = [ObjectId(group_id) for group_id in follower_group_ids]

        groups_found = list(groupRepository.find(
            {"_id": {"$in": follower_group_ids}}))

        follower_list = [GroupSchema(**group) for group in groups_found]

        return [follower.toJson() for follower in follower_list]
    except PyMongoError as error:
        raise InternalServerError(str(error))
