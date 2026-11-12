from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.dependencies.group_auth import assert_group_owner, require_authenticated_uid
from app.repositories import WhatsappLinkRepository as link_repo
from app.utils.ResponseUtils import error_json_response, get_successful_response

whatsappLinksRouter = APIRouter(prefix="/group")


def _set_link_status(request: Request, group_id: str, uid: str, new_status: str):
    try:
        caller_uid = require_authenticated_uid(request)
        try:
            assert_group_owner(caller_uid, group_id)
        except InvalidId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="group_id is not a valid group id",
            )
        if not link_repo.find(uid, group_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="WhatsApp link not found",
            )
        link_repo.set_status(uid, group_id, new_status, caller_uid)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(
                {"uid": uid, "group_id": group_id, "status": new_status}
            ),
        )
    except HTTPException as e:
        return error_json_response(e)


@whatsappLinksRouter.post(
    "/{group_id}/whatsapp-links/{uid}/disable",
    description="Owner disables a member's WhatsApp link",
    tags=["WhatsApp Links"],
)
def disable_link(request: Request, group_id: str, uid: str):
    return _set_link_status(request, group_id, uid, "disabled")


@whatsappLinksRouter.post(
    "/{group_id}/whatsapp-links/{uid}/enable",
    description="Owner re-enables a member's WhatsApp link",
    tags=["WhatsApp Links"],
)
def enable_link(request: Request, group_id: str, uid: str):
    return _set_link_status(request, group_id, uid, "active")
