from fastapi import HTTPException
from app.repositories import InvitationRepository as inviteRepository
from app.schemas.Invitations import InvitationsSchema, InvitationStatus
from typing import Dict, Any, List
from app.repositories import GroupRepository as groupRepository
from app.schemas.Groups import GroupSchema
from app.repositories import ListsRepository as listRepository
from app.schemas.Lists import ListsSchema


def change_status(census_id: str, new_status: str):
    try:
        invites_found = list(inviteRepository.find_all_by_census_id(census_id))
        modified_invites = []
        modified_count = 0

        inviter_groups: List[str] = []

        for invite in invites_found:
            invite_data = InvitationsSchema(**invite)
            invite_data.change_status(new_status)

            inviter_groups.append(invite_data.creator_group)

            invite_json = invite_data.toJson()
            invite_json.pop('_id')
            modified_count += inviteRepository.edit(
                invite_data.id, {"inviteStatus": invite_json["inviteStatus"]}).modified_count
            modified_invites.append(invite_data.id)

        if new_status == InvitationStatus.ACCEPTED.value and len(inviter_groups) > 0:
            _append_created_group_to_lists(
                census_id, inviter_groups, invite_data.user)
        return {"modified_count": modified_count, "modified_invites": modified_invites, "inviter_groups": inviter_groups}
    except HTTPException as e:
        raise HTTPException(
            status_code=500, detail=f"Error changing the invite status {e}")


def _append_created_group_to_lists(census_id: str, inviter_groups: List[str], inviter_group_id: str) -> int:
    groups_related_to_census = list(groupRepository.find(
        {"censusReference": census_id}))

    group: GroupSchema

    if len(groups_related_to_census) > 0:
        group = GroupSchema(**groups_related_to_census[0])
        modified_lists: int = 0
        for inviter_group_id in inviter_groups:
            lists = list(listRepository.find(
                {"group_id": inviter_group_id, "name": "Mi Red", "is_priority": True}))

            for group_list in lists:
                userList = ListsSchema(**group_list)
                modified_lists += listRepository.insert_group_to_list(
                    userList.id, group.id).modified_count

    return modified_lists


def find(user_id: str | None, group_id: str | None, status: str | None, final_contact_info: str | None):
    try:
        filters: Dict[str, Any] = {}

        if user_id is not None:
            filters["user"] = user_id

        if group_id is not None:
            filters["creator_group"] = group_id

        if status is not None:
            try:
                invite_status = InvitationStatus[status]
                filters["inviteStatus"] = invite_status.value
            except KeyError:
                raise HTTPException(
                    status_code=400, detail=f"{status} is not a valid invitation status")

        if final_contact_info is not None:
            filters["finalContactInfo"] = final_contact_info

        invites_found = list(inviteRepository.find(filters))

        formatted_invites = []

        for invite in invites_found:
            invite_data = InvitationsSchema(**invite)
            formatted_invites.append(invite_data.toJson())

        return formatted_invites
    except HTTPException as e:
        raise HTTPException(
            status_code=500, detail=f"Error finding invites {e}")
