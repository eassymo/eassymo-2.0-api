from app.repositories import GroupRepository as groupRepository
from app.repositories import CensusRepository as censusRepository
from app.repositories import UserRepository as userRepository
from app.repositories import ListsRepository as listRepository
from app.repositories import PartRequestInviteRepository as partRequestInviteRepository
from app.schemas.Groups import GroupSchema
from app.schemas.Census import CensusSchema
from app.schemas.Lists import ListsSchema
from app.schemas.Users import UserSchema
from app.schemas.RequestInvites import RequestInviteStatus
from pymongo.errors import PyMongoError
from fastapi import HTTPException, Request, status
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
from app.dto.group_dto import EditGroupDto
from bson import ObjectId
from app.schemas.GeoJsonLocation import GeoJson
import re

GROUP_SEARCH_FIELDS = ("name", "address", "city", "state", "email")
GROUP_SEARCH_RESULT_LIMIT = 50


def _build_group_search_filter(search_argument: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Case-insensitive substring search across common group fields.
    Multi-word queries require every token to match at least one field.
    """
    if search_argument is None:
        return None

    search_term = search_argument.strip()
    if not search_term:
        return None

    tokens = [token for token in re.split(r"\s+", search_term) if token]
    if not tokens:
        return None

    token_conditions: List[Dict[str, Any]] = []
    for token in tokens:
        pattern = re.escape(token)
        token_conditions.append({
            "$or": [
                {field: {"$regex": pattern, "$options": "i"}}
                for field in GROUP_SEARCH_FIELDS
            ]
        })

    if len(token_conditions) == 1:
        return token_conditions[0]

    return {"$and": token_conditions}


def _compose_group_find_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    conditions: List[Dict[str, Any]] = []

    if "is_callcenter" in filters:
        conditions.append({"is_callcenter": filters["is_callcenter"]})

    text_search = _build_group_search_filter(filters.get("search_argument"))
    if text_search is not None:
        conditions.append(text_search)

    if not conditions:
        return {}

    if len(conditions) == 1:
        return conditions[0]

    return {"$and": conditions}


def create_group(
    group: GroupSchema,
    censusReference: str | None,
    user_id: str,
    mysql_db: Optional["Session"] = None,
):

    group_data = {
        **group.dict(),
        "since": str(group.since),
        "censusReference": censusReference,
        "type": group.type,
        "group_store_type": group.type,
        "users": [user_id],
        "owner": user_id
    }

    created_group = groupRepository.insert(group_data)
    created_group_id = str(created_group.inserted_id)

    if mysql_db is not None:
        try:
            from app.services import GroupConfigService as groupConfigService

            groupConfigService.initialize_sistemas_for_new_group(
                created_group_id, mysql_db
            )
        except Exception:
            pass

    userRepository.add_user_group(user_id, created_group_id)

    user_lists = list(listRepository.find(
        {"user_uid": user_id, "group_id": created_group_id}))

    if len(user_lists) == 0:
        user_list = ListsSchema(
            group_id=created_group_id,
            name="Mi Red",
            groups=[],
            is_priority=True,
            user_uid=user_id
        ).toJson()

        user_list.pop('_id')
        listRepository.insert(user_list)

    if censusReference is not None:
        census_json = censusRepository.find_by_id(censusReference)
        census_data = CensusSchema(**census_json)
        census_data.Entity_Status = "1"
        censusRepository.update(
            censusReference, {"group_reference_id": created_group_id})
    else:
        census_data = CensusSchema(
            Census_Country="Mexico",
            Entity_Address_City=group.city,
            Entity_Location_State=group.state,
            Entity_Address_Short=group.address,
            Entity_Name=group.name,
            Entity_Type=group.type,
            Entity_Visible="Y",
            Entity_Status="Y",
            group_reference_id=created_group_id,
            location=group.location
        )
        census_json = census_data.dict()
        censusRepository.insert(census_json)

    group_data["_id"] = str(group_data["_id"])

    return {"message": "ok", "body": group_data}


def find(request: Request, filters: Dict[str, Any]) -> List[GroupSchema]:
    try:
        user = request.state._state.get('user')
        groupSelected = request.state._state.get('groupSelected')

        search_filters = _compose_group_find_filters(filters)

        groups_cursor = groupRepository.find(search_filters)
        if filters.get("search_argument"):
            groups_cursor = groups_cursor.sort("name", 1).limit(GROUP_SEARCH_RESULT_LIMIT)

        groups_data = list(groups_cursor)

        groups: List[GroupSchema] = []

        for group_data in groups_data:
            group = GroupSchema(**group_data)

            search_filters = {
                "inviter_user": user.get('uid'),
                "inviter_group": groupSelected,
                "invited_group": str(group.id),
                "$or": [
                    {
                        "status": RequestInviteStatus.CREATED.value
                    },
                    {
                        "status": RequestInviteStatus.ACCEPTED.value
                    }
                ]
            }

            if "parent_request_id" in filters and filters["parent_request_id"] != None:
                search_filters["parent_request_id"] = filters["parent_request_id"]

            invites_data_found = list(
                partRequestInviteRepository.find(search_filters))

            group.can_be_invited = len(invites_data_found) == 0

            groups.append(group)

        return groups
    except (PyMongoError, HTTPException) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


def find_by_user_id(uid: str):
    try:
        group_list = list(groupRepository.find_by_user(uid))
        return {"message": "ok", "body": group_list}
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail="Error while finding groups")


def find_users_by_groups_ids(groups_ids: List[str]):
    try:
        user_string_ids = set()
        for group_id in groups_ids:
            users_from_group = groupRepository.find_users_by_group_id(group_id)
            user_string_ids.update(users_from_group["users"])

        return list(user_string_ids)
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding users {err}')


def find_users_by_groups_ids_v2(groups_ids: List[str]) -> List[Dict[str, Any]]:
    try:
        group_ids = [ObjectId(group_id) for group_id in groups_ids]
        groups_data = list(groupRepository.find(
            {"_id": {"$in": group_ids}}, {"_id": 1, "users": 1}))

        groups_found: List[Dict[str, Any]] = []

        for group_data in groups_data:
            groups_found.append({**group_data, "_id": str(group_data["_id"])})

        return groups_found
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding user from groups {err}')


def find_group_by_id(id: str):
    try:
        group_info = groupRepository.find_by_id(id)
        if group_info != None:
            group = GroupSchema(**group_info)
            return group.toJson()

        return None
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding group {err}')


def edit_group_by_id(user_uid: str, id: str, payload: EditGroupDto):
    try:
        group_info = groupRepository.find_by_id(id)
        if group_info != None:
            group = GroupSchema(**group_info)

            if user_uid != group.owner:
                raise HTTPException(
                    status_code=401, detail='Only the owner of the group can edit information')

            edited_group = groupRepository.edit_group(id, payload.model_dump())

            if edited_group != None:
                group = GroupSchema(**edited_group)
                return group.toJson()

    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while editing group {err}')


def add_employee_to_group(group_id: str, employee_uid: str) -> str | None:
    try:
        group_ifo = groupRepository.find_by_id(group_id)
        employee_info = list(userRepository.find_by_uid(employee_uid))

        employee_groups = []

        if len(employee_info) > 0:
            employee_data = employee_info[0]
            employee_groups = [str(group["_id"])
                               for group in employee_data["groups"]]
            employee_data["groups"] = employee_groups
            employee_info[0] = employee_data

        if group_ifo != None and len(employee_info) > 0:
            employee = UserSchema(**employee_info[0])
            group = GroupSchema(**group_ifo)
            group.add_user_to_group(employee.uid)
            employee.add_group_to_user(group_id)

            employee_data = employee.toJson()
            employee_data.pop("_id")

            group_data = group.toJson()
            group_data.pop("_id")
            print(group_data)
            modified_users = userRepository.update_user(
                employee.uid, employee_data).modified_count
            modified_groups = groupRepository.edit_group(group.id, group_data)

            return {
                "user": employee_data if modified_users > 0 else None,
                "group": group if modified_groups != None else None
            }
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while adding employee to group {err}')


def find_users_by_group_id(group_id: str) -> List[Dict[str, Any]]:
    """
    Retrieves all users that belong to a specific group.

    Args:
        group_id: The ID of the group to find users for

    Returns:
        A list of user data dictionaries

    Raises:
        HTTPException: If there's an error retrieving the users
    """
    try:
        # First get the group to verify it exists
        group_info = groupRepository.find_by_id(group_id)
        if group_info is None:
            raise HTTPException(
                status_code=404, detail=f"Group with ID {group_id} not found")

        group = GroupSchema(**group_info)

        # If the group has no users, return an empty list
        if not group.users or len(group.users) == 0:
            return []

        # Get detailed user information for each user in the group
        users_data = []
        for user_uid in group.users:
            user_info = list(userRepository.find_by_uid(user_uid))
            if user_info and len(user_info) > 0:
                # Format the user data
                user_data = user_info[0]
                # Convert ObjectId to string if present
                if "_id" in user_data and not isinstance(user_data["_id"], str):
                    user_data["_id"] = str(user_data["_id"])

                # Format groups if present
                if "groups" in user_data and isinstance(user_data["groups"], list):
                    user_data["groups"] = [GroupSchema(
                        **g).toJson() if not isinstance(g, str) else g for g in user_data["groups"]]

                users_data.append(user_data)

        return users_data
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding users for group {err}')


def transfer_ownership(request: Request, group_id: str, new_owner: str):
    try:
        user = request.state._state.get('user')

        group_info = groupRepository.find_by_id(group_id)
        if group_info != None:
            group = GroupSchema(**group_info)
            user = _find_user(new_owner)

            user.add_group_to_user(group.id)

            if group.owner == user["uid"]:
                group.owner = new_owner
                group.add_user_to_group(new_owner)

                group_payload = group.toJson()

                group_payload.pop("_id")
                edited_group = groupRepository.edit_group(
                    group.id, group_payload)

                return GroupSchema(**edited_group).toJson()
            else:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                    detail="Only the owner can change the ownership of the group")
        print(user)

    except (HTTPException, PyMongoError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f'Error while transfering ownership of group {e}')


def _find_user(uid: str) -> UserSchema | None:
    try:
        user_info = userRepository.find_one({"uid": uid})
        if user_info != None:
            user = UserSchema(**user_info)
            return user
        return None
    except (HTTPException, PyMongoError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='Error while getting user ')


def find_bulk(group_ids: List[str]) -> List[Dict[str, Any]]:
    try:

        ids: List[ObjectId] = [ObjectId(group_id) for group_id in group_ids]

        groups = list(groupRepository.find({"_id": {"$in": ids}}))

        groups_objs: List[GroupSchema] = [GroupSchema(**group) for group in groups]
        
        return [group.toJson() for group in groups_objs]
    except (HTTPException) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='Error while getting groups in bulk')
