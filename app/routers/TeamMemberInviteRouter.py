from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, Request, status, HTTPException
from app.repositories import TeamMemberInviteRepository as teamMemberInviteRepository
from app.schemas.TeamMemberInvite import TeamMemberInvite, TeamMemberInviteStatus
from app.services import TeamMemberInviteService as teamMemberInviteService
from app.services import authz
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder

teamMemberInviteRouter = APIRouter(prefix="/team-member-invite")


def _assert_can_invite(request: Request, payload: TeamMemberInvite) -> None:
    caller = authz.caller_uid(request)
    group_ref = getattr(payload.group, "id", payload.group)
    group_id = authz.selected_group(request, override=str(group_ref) if group_ref else None)
    role_value = authz.resolve_role_value(payload.role)
    ok, reason = authz.can_invite_with_role(caller, group_id, role_value, request)
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)
    payload.inviter_user = caller


def _assert_invite_role_still_assignable(invite_id: str) -> None:
    invite = teamMemberInviteRepository.find_by_id(invite_id)
    if not invite:
        return  # the service reports the missing invite
    # Invites were checked when created (also before phase 1 rules existed), so accepting only
    # requires the role to still exist, be active and fit the group.
    group_id = str(invite.get("group") or "")
    role, _ = authz.role_fits_group(group_id, authz.resolve_role_value(invite.get("role")))
    if not role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El rol de la invitación ya no está disponible")


@teamMemberInviteRouter.post("", tags=["Team Member Invite"])
@teamMemberInviteRouter.post("/", include_in_schema=False)
def insert(request: Request, payload: TeamMemberInvite = Body()):
    try:
        _assert_can_invite(request, payload)
        response = teamMemberInviteService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (Exception, HTTPException) as e:
        return JSONResponse(status_code=getattr(e, 'status_code', None) or status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))


@teamMemberInviteRouter.get("/{id}", tags=["Team Member Invite"])
def find_by_id(id: str):
    try:
        response = teamMemberInviteService.find_by_id(id)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))

    except (Exception, HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))


@teamMemberInviteRouter.put("/{id}/accept", tags=["Team Member Invite"])
def accept_team_member_invite(id: str, payload=Body(...)):
    try:
        _assert_invite_role_still_assignable(id)
        response = teamMemberInviteService.change_invite_status(
            id, TeamMemberInviteStatus.ACCEPTED, payload["user_uid"])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (Exception, HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))


@teamMemberInviteRouter.put("/{id}/reject", tags=["Team Member Invite"])
def reject_team_member_invite(id: str, payload=Body(...)):
    try:
        response = teamMemberInviteService.change_invite_status(
            id, TeamMemberInviteStatus.REJECTED  , payload["user_uid"])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (Exception, HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))
