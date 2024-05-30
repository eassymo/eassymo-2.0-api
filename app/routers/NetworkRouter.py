from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query
from app.services import NetworkService as networkService
from app.schemas.Invitations import InvitationsSchema
from app.utils import TypeUtilities as typeUtilities
from typing import Optional
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder


networkRouter = APIRouter(prefix="/network")


@networkRouter.post("/send-invite", response_description="response that we get from the meta api when we send an invite", tags=["invite"])
def send_invite(inviteId: Optional[str] = Query(None, title="inviteId", description="invite id used for re sending the invite"), payload: InvitationsSchema = Body(...)):
    response = networkService.sendNetworkInvitationMessage(inviteId, payload)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)


@networkRouter.get("/user-invites/{id}", response_description="user invites", tags=["invite"])
def get_user_invites(id: str):
    response = typeUtilities.parse_json(networkService.get_user_invites(id))
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)


@networkRouter.get("/user-network", response_description="User network, this includes all of the invites and all of the members connected to the user group", tags=["invite"])
def get_user_network(user_uid: Optional[str] = Query(None, title="user_uid", description="user uid used for checking the users that are a part of the user network")):
    response = typeUtilities.parse_json(
        networkService.get_user_network(user_uid))
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
