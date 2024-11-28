from fastapi import HTTPException
from app.repositories import InvitationRepository as inviteRepository
from app.schemas.Invitations import InvitationsSchema, InvitationStatus
from typing import Dict, Any


def change_status(census_id: str, new_status: str):
    try:
        invites_found = list(inviteRepository.find_all_by_census_id(census_id))
        modified_invites = []
        modified_count = 0

        print(invites_found)

        for invite in invites_found:
            invite_data = InvitationsSchema(**invite)
            invite_data.change_status(new_status)

            invite_json = invite_data.toJson()
            invite_json.pop('_id')
            modified_count += inviteRepository.edit(
                invite_data.id, {"inviteStatus": invite_json["inviteStatus"]}).modified_count
            modified_invites.append(invite_data.id)

        return {"modified_count": modified_count, "modified_invites": modified_invites}
    except HTTPException as e:
        raise HTTPException(
            status_code=500, detail=f"Error changing the invite status {e}")


def find(user_id: str | None, group_id: str | None, status: str | None):
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

        invites_found = list(inviteRepository.find(filters))

        formatted_invites = []

        for invite in invites_found:
            invite_data = InvitationsSchema(**invite)
            formatted_invites.append(invite_data.toJson())

        return formatted_invites
    except HTTPException as e:
        raise HTTPException(
            status_code=500, detail=f"Error finding invites {e}")
