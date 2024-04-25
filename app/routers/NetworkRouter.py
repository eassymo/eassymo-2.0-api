from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query
from app.services import NetworkService as networkService
from app.schemas.Invitations import InvitationsSchema
from app.utils import TypeUtilities as typeUtilities
from typing import Optional


networkRouter = APIRouter(prefix="/network")


@networkRouter.post("/send-invite", response_description="response that we get from the meta api when we send an invite", tags=["invite"])
def send_invite(inviteId: Optional[str] = Query(None, title="inviteId", description="invite id used for re sending the invite"), payload: InvitationsSchema = Body(...)):
    response = networkService.sendNetworkInvitationMessage(inviteId, payload)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)


@networkRouter.get("/user-invites/{id}", response_description="user invites", tags=["invite"])
def get_user_invites(id: str):
    response = typeUtilities.parse_json(networkService.get_user_invites(id))
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)
