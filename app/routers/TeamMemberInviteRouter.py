from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, HTTPException
from app.schemas.TeamMemberInvite import TeamMemberInvite, TeamMemberInviteStatus
from app.services import TeamMemberInviteService as teamMemberInviteService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder

teamMemberInviteRouter = APIRouter(prefix="/team-member-invite")


@teamMemberInviteRouter.post("", tags=["Team Member Invite"])
def insert(payload: TeamMemberInvite = Body()):
    try:
        response = teamMemberInviteService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (Exception, HTTPException) as e:
        return JSONResponse(status_code=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))


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
