from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status
from app.services import NetworkService as networkService
from app.schemas.Invitations import InvitationsSchema
from app.utils import TypeUtilities as typeUtilities


networkRouter = APIRouter(prefix="/network")


@networkRouter.post("/send-invite", response_description="response that we get from the meta api when we send an invite", tags=["invite"])
def send_invite(payload: InvitationsSchema = Body(...)):
    response = networkService.sendNetworkInvitationMessage(payload)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)

@networkRouter.get("/user-invites/{id}")
def get_user_invites(id: str):
    response = typeUtilities.parse_json(networkService.get_user_invites(id))
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)