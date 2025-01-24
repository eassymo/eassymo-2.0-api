from app.repositories import GroupRepository as groupRepository
from app.repositories import CensusRepository as censusRepository
from app.repositories import UserRepository as userRepository
from app.repositories import ListsRepository as listRepository
from app.repositories import PartRequestInviteRepository as partRequestInviteRepository
from app.schemas.Groups import GroupSchema
from app.schemas.Census import CensusSchema
from app.schemas.Lists import ListsSchema
from app.schemas.RequestInvites import RequestInviteStatus
from pymongo.errors import PyMongoError
from fastapi import HTTPException, Request
from typing import List, Dict, Any
from app.dto.group_dto import EditGroupDto


def create_group(group: GroupSchema, censusReference: str | None, user_id: str):

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
            group_reference_id=created_group_id
        )
        census_json = census_data.dict()
        censusRepository.insert(census_json)

    group_data["_id"] = str(group_data["_id"])

    return {"message": "ok", "body": group_data}


def find(request: Request, filters: Dict[str, Any]) -> List[GroupSchema]:
    try:
        user = request.state._state.get('user')
        groupSelected = request.state._state.get('groupSelected')

        search_filters = {}
        if (filters["search_argument"] != None):
            search_filters["$text"] = {
                "$search": filters["search_argument"]
            }

        groups_data = list(groupRepository.find(search_filters))

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

            invites_data_found = list(partRequestInviteRepository.find(search_filters))

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
