from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any

from fastapi import HTTPException, status
from pymongo.errors import PyMongoError
from bson import ObjectId

from app.repositories import GroupRepository as groupRepository
from app.repositories import TeamMemberInviteRepository as teamMemberInviteRepository
from app.repositories import RolesRepository as rolesRepository
from app.repositories import UserRepository as userRepository
from app.schemas.Groups import GroupSchema
from app.schemas.Roles import RolesSchema
from app.schemas.Users import UserSchema
from app.schemas.TeamMemberInvite import TeamMemberInvite, TeamMemberInviteStatus, TeamMemberInviteStatusChange
from app.schemas.WhatasppMessage import WhatsappMessage, WhatsappTemplate
from app.services.WhatsappService import WhatsappService

whatsapp_service = WhatsappService()


def insert(team_member_invite: TeamMemberInvite):
    try:
        sender_group_info = groupRepository.find_by_id(
            team_member_invite.group)

        sender_group: GroupSchema = GroupSchema(**sender_group_info)

        can_send_invite = _verify_can_send_invite(
            team_member_invite) if team_member_invite.is_public == False else True

        if can_send_invite and team_member_invite.is_public == False:
            team_member_invite.status_changes.append(
                TeamMemberInviteStatusChange(
                    status=TeamMemberInviteStatus.SENT, timestamp=datetime.now(ZoneInfo('UTC')))
            )
            inserted_invite = teamMemberInviteRepository.insert(
                team_member_invite).inserted_id

            whatsapp_message = WhatsappMessage(
                to=team_member_invite.contact_method,
                template=WhatsappTemplate(
                    name="HX9c1c720b428fdf6e29ecd203b0762e42",
                    variables=[sender_group.name, str(inserted_invite)]
                )
            )

            whatsapp_message_sent_data: Dict[str, Any]
            try:
                whatsapp_message_sent_data = whatsapp_service.send_template_message(
                    whatsapp_message)
            except Exception as e:
                raise Exception(
                    'Error while sending team invite whatsapp message')

            return {
                "invite_id": str(inserted_invite),
                "whatsapp_message_sent_data": whatsapp_message_sent_data
            }
        elif can_send_invite and team_member_invite.is_public == True:
            team_member_invite.status_changes.append(
                TeamMemberInviteStatusChange(
                    status=TeamMemberInviteStatus.SENT, timestamp=datetime.now(ZoneInfo('UTC')))
            )
            inserted_invite = teamMemberInviteRepository.insert(
                team_member_invite).inserted_id

            return {
                "invite_id": str(inserted_invite),
            }

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Cant send team invite another already exists')

    except PyMongoError as err:
        raise Exception(f'Failed to insert team member invite{str(err)}')


def _verify_can_send_invite(team_member_invite: TeamMemberInvite) -> bool:
    try:
        seven_days_ago = datetime.now() - timedelta(days=7)

        seven_days_ago_str = seven_days_ago.isoformat()

        invites_found = list(teamMemberInviteRepository.find(
            {
                "group": team_member_invite.group,
                "inviter_user": team_member_invite.inviter_user,
                "role": team_member_invite.role,
                "timestamp": {"$gte": seven_days_ago_str}
            }))

        return len(invites_found) == 0
    except PyMongoError as err:
        raise Exception(f'Failed to verify if invite can be sent {str(err)}')


def change_invite_status(invite_id: str, new_status: TeamMemberInviteStatus, user_uid: str):
    try:
        match new_status:
            case TeamMemberInviteStatus.ACCEPTED:
                return _accept_invite(invite_id, user_uid)
            case TeamMemberInviteStatus.REJECTED:
                return _reject_invite(invite_id)
    except PyMongoError as err:
        raise Exception(f'Failed to verify if invite can be sent {str(err)}')


def _accept_invite(invite_id: str, user_uid: str):
    try:
        invite_id = ObjectId(invite_id)
        invite_data = teamMemberInviteRepository.find_by_id(str(invite_id))
        if invite_data != None:

            invite = TeamMemberInvite(**invite_data)

            invite.change_status(TeamMemberInviteStatus.ACCEPTED.value)
            print(invite)
            _add_user_to_group(invite, user_uid)
            _add_group_to_user(user_uid, invite.group)

            invite_payload = invite.toJson()
            invite_payload.pop('id')

            modified_invite = teamMemberInviteRepository.find_one_and_update(
                str(invite_id), invite_payload)

            return TeamMemberInvite(**modified_invite).toJson()

        raise Exception(f'Error invite with id {invite_id} not found')

    except Exception as err:
        raise Exception(f'Error while changing invite status {err}')


def _add_user_to_group(invite: TeamMemberInvite, user_uid: str):
    try:
        group_data = groupRepository.find_by_id(invite.group)

        group = GroupSchema(**group_data)

        group.add_user_to_group(user_uid)

        group_payload = group.toJson()
        group_payload.pop('_id')

        groupRepository.edit_group(invite.group, group_payload)
    except Exception as err:
        raise Exception(
            f'Error while changing invite status adding user to group {err}')


def _add_group_to_user(user_uid: str, group_id: str):
    try:
        user_info = list(userRepository.find_by_uid(user_uid))

        if user_info != None and len(user_info) > 0:
            user = UserSchema(**user_info[0])
            user_groups = [group['_id'] for group in user_info[0]['groups']]
            user.groups = user_groups
            user.add_group_to_user(group_id)
            user_payload = user.toJson()
            user_payload.pop('_id')
            userRepository.update_user(user_uid, user_payload)
    except Exception as err:
        raise Exception(
            f'Error while changing invite status adding group to user {err}')


def _reject_invite(invite_id: str):
    try:
        invite_id = ObjectId(invite_id)
        invite_data = teamMemberInviteRepository.find_by_id(invite_id)

        if invite_data != None:
            invite = TeamMemberInvite(**invite_data)
            invite.change_status(TeamMemberInviteStatus.REJECTED.value)

            invite_payload = invite.toJson()
            invite_payload.pop('id')

            modified_invite = teamMemberInviteRepository.find_one_and_update(
                invite_id, invite_payload)

            return TeamMemberInvite(**modified_invite).toJson()

        raise Exception(f'Error invite with id {invite_id} not found')
    except Exception as err:
        raise Exception(f'Error while changing invite status {err}')


def find_by_id(id: str) -> Dict[str, Any]:
    try:
        invite_data = teamMemberInviteRepository.find_by_id(id)
        if invite_data != None:
            team_member_invite = TeamMemberInvite(**invite_data)

            group_info = groupRepository.find_by_id(team_member_invite.group)
            if group_info != None:
                group = GroupSchema(**group_info)
                team_member_invite.group = group
            else:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=f"Group related to invite is not found")

            role_info = rolesRepository.find_by_id(team_member_invite.role)

            if role_info != None:
                role = RolesSchema(**role_info)

                team_member_invite.role = role.toJson()

            user_info = list(userRepository.find_by_uid(
                team_member_invite.inviter_user))
            if user_info != None and len(user_info) > 0:
                user = UserSchema(**user_info[0])

                team_member_invite.inviter_user = {
                    "name": user.name,
                    "phone": user.phone,
                    "email": user.email,
                    "uid": user.uid
                }

            return team_member_invite.toJson()

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"invite with id {id} not found")
    except (PyMongoError, HTTPException) as e:
        raise (HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
               detail=f'Error while fetching the invite {str(e)}'))
