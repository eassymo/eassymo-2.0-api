from fastapi import APIRouter, Body, status, Query, HTTPException, Request
from app.schemas.Chat import Chat
from app.schemas.RequestInvites import RequestInvite
from app.services import PartRequestInviteService as partRequestInviteService
from fastapi.responses import JSONResponse
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

partRequestInviteRouter = APIRouter(prefix="/partRequestInvite")


@partRequestInviteRouter.post("", description="Insert a new part request invite", tags=["partRequestInvite"])
def insert(partRequestInvite: RequestInvite):
    try:
        response = partRequestInviteService.insert(partRequestInvite)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response.toJson()))
    except (HTTPException, Exception) as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@partRequestInviteRouter.get("/{id}", description="Get a part request invite by id", tags=["partRequestInvite"])
def find_by_id(id: str):
    try:
        response = partRequestInviteService.find_by_id(id)
        if response != None:
            return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response.toJson()))
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(None))
    except (HTTPException, Exception) as e:
        return JSONResponse(content=get_unsuccessful_response(e))
    

@partRequestInviteRouter.put("/update-status", description="Edit a part request invite", tags=["partRequestInvite"])
def update_status(request: Request, payload = Body(...)):
    try:
        invited_group = request.state._state.get("groupSelected")
        response = partRequestInviteService.update_status(payload["inviter_group"], invited_group, payload["parent_request_id"], payload["status"])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except (HTTPException, Exception) as e:
        return JSONResponse(content=get_unsuccessful_response(e))