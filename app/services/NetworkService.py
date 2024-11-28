from fastapi import HTTPException
from app.schemas.Invitations import InvitationsSchema, InvitationStatus
from app.repositories import InvitationRepository as invitationRepository
from app.repositories import ListsRepository as listRepository
from pymongo.errors import PyMongoError
from datetime import datetime
from typing import List, Dict, Any
from app.services.WhatsappService import WhatsappService
from app.schemas.WhatasppMessage import WhatsappMessage, WhatsappTemplate
from app.schemas.Invitations import InvitationsSchema


whatsapp_service = WhatsappService()


def sendNetworkInvitationMessage(id: str | None, inviteData: InvitationsSchema):
    if (id != None):
        invite = invitationRepository.find_by_id(id)
        inviteData = InvitationsSchema(**invite)

    whatsapp_message = WhatsappMessage(
        to=inviteData.finalContactInfo,
        template=WhatsappTemplate(
            name="HXc4c0c5dd59125e6d3e0e1b5bcf5df9a3",
            variables=[inviteData.censusUser.Entity_Name, inviteData.censusId]
        )
    )

    whatsapp_message_sent_data: Dict[str, Any]

    try:
        whatsapp_message_sent_data = whatsapp_service.send_template_message(
            whatsapp_message)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error sending Whatsapp message {e}")

    try:

        invite_data = {
            "user": inviteData.user,
            "userName": inviteData.userName,
            "inviteStatus": InvitationStatus.SENT.value,
            "censusId": inviteData.censusId,
            "censusUser": inviteData.censusUser.dict(),
            "type": inviteData.type.value,
            "finalContactInfo": inviteData.finalContactInfo,
            "creator_group": inviteData.creator_group,
            "createdAt": datetime.utcnow(),
            "lastSent": datetime.utcnow(),
            "whatsapp_message_data": whatsapp_message_sent_data
        }

        if (id != None):
            invite_data = {**invite_data, "createdAt": inviteData.createdAt}
            invitationRepository.edit(id, invite_data)
            return id
        else:
            id = invitationRepository.insert(invite_data).inserted_id
            return str(id)
    except HTTPException as exception:
        raise HTTPException(
            status_code=500, detail=f"Error sending Invite {exception}")


def get_user_invites(id: str):
    try:
        invites = list(invitationRepository.find_user_invites(id))
        return {"message": "ok", "body": invites}
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail="Item not found")


def get_user_network(user_uid: str):
    try:
        invites = list(invitationRepository.find_user_invites(user_uid))
        user_network = list(
            listRepository.find_lists_by_users_with_groups_info(user_uid))

        invites = format_invites(invites)
        user_network = format_user_network(user_network)

        return {"invites": invites, "lists": user_network}

    except PyMongoError as e:
        raise HTTPException(
            status_code=500, detail="Error while building user network")


def format_invites(invites):
    formatted_list = []
    for invite in invites:
        formatted_list.append({
            **invite,
            "_id": str(invite["_id"])
        })
    return formatted_list


def format_user_network(user_network):
    formatted_list = []
    for network in user_network:
        formatted_list.append({
            **network,
            "_id": str(network["_id"]),
            "groups": [{**group, "_id": str(group["_id"])} for group in network["groups"]]
        })
    return formatted_list
