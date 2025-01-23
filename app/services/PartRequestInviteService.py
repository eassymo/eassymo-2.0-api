from app.schemas.RequestInvites import RequestInvite, RequestInviteStatus
from fastapi import HTTPException, status
from app.repositories import PartRequestRepository, PartRequestInviteRepository
from app.schemas.PartRequest import PartRequest, PartRequestStatus
from pymongo.errors import PyMongoError
from bson import ObjectId
from typing import List, Dict, Any


def insert(partRequestInvite: RequestInvite) -> RequestInvite:
    try:
        part_request_data = list(PartRequestRepository.find({
            "specific_order_uid": partRequestInvite.parent_request_id
        }, {}))

        if len(part_request_data) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="part request with that id is not found")

        for part_request in part_request_data:
            part_request_item = PartRequest(**part_request)

            if part_request_item.status.value != PartRequestStatus.CREATED.value:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="cannot create invites for part requests that have a status different that created")

        existing_invite = list(PartRequestInviteRepository.find(
            {
                "parent_request_id": partRequestInvite.parent_request_id,
                "inviter_group": partRequestInvite.inviter_group,
                "inviter_user": partRequestInvite.inviter_user,
                "invited_group": partRequestInvite.invited_group
            }
        ))

        if len(existing_invite) > 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Cannot create an invite since one already exists")
        
        part_request_invite_payload = partRequestInvite.toJson()

        part_request_invite_payload.pop('_id')

        inserted_id = PartRequestInviteRepository.insert(part_request_invite_payload).inserted_id

        part_request_invite_data = PartRequestInviteRepository.find_by_id(
            inserted_id)

        return RequestInvite(**part_request_invite_data)
    except (HTTPException, PyMongoError) as e:
        raise HTTPException(e)


def update_status(inviter_group: str, invited_group: str, parent_request_id: str, status: str):
    try:

        part_requests_modified: List[Dict[str, Any]] = []

        part_request_invites_data = list(PartRequestInviteRepository.find({
            "inviter_group": inviter_group,
            "invited_group": invited_group,
            "parent_request_id": parent_request_id
        }))
        
        for part_request_invite_item in part_request_invites_data:
            part_request_invite: RequestInvite = RequestInvite(**part_request_invite_item)
            part_request_invite.change_status(status)

            part_request_json = part_request_invite.toJson()

            part_request_id = ObjectId(part_request_json["_id"])

            part_request_json.pop('_id')

            modified_part_request_invite = PartRequestInviteRepository.find_one_and_update(part_request_id, part_request_json)
            
            modified_invite = RequestInvite(**modified_part_request_invite)

            part_requests_modified.append(modified_invite.toJson())

            return part_requests_modified
    except (HTTPException) as e:
        raise HTTPException(e)


def find_by_id(part_request_invite_id: str) -> RequestInvite:
    try:
        part_request_invite_id = ObjectId(part_request_invite_id)
        part_request_invite_data = PartRequestInviteRepository.find_by_id(
            part_request_invite_id)

        if part_request_invite_data != None:
            part_request_invite = RequestInvite(**part_request_invite_data)
            return part_request_invite

        return None
    except (HTTPException) as e:
        raise HTTPException(e)