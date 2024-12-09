from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, Query
from typing import Optional
from app.services import InviteService as inviteService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder


inviteRouter = APIRouter(prefix="/invite")


@inviteRouter.get("", description="gets the invites according to the filters", tags=["Invites"])
def find(
    user_id: Optional[str] = Query(
        None, title="user_id", description="User creator of the invite"),
    group_id: Optional[str] = Query(
        None, title="group_id", description="Group creator of the invite"), 
    status: Optional[str] = Query(
        None, title="status", description="Status of the invite - must be one of the valid InvitationStatus values"),
    final_contact_info: Optional[str] = Query(None, title="final_contact_info", description="The contact info with which the invitation was sent")
):
    try:
        invites = inviteService.find(user_id, group_id, status, final_contact_info)
        return JSONResponse(get_successful_response(jsonable_encoder(invites)))
    except Exception as e:
        return JSONResponse(get_unsuccessful_response(e))


@inviteRouter.put("/change_status/{census_id}", description="Change the status of an invite", tags=["Invites"])
def change_status(census_id: str, data=Body(...)):
    try:
        response = inviteService.change_status(census_id, data["status"])
        return JSONResponse(get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(get_unsuccessful_response(e))
