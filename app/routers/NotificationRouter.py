from typing import Optional

from fastapi import APIRouter, Body, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.dependencies.group_auth import assert_group_membership, require_authenticated_uid
from app.services import NotificationService as notificationService
from app.utils.ResponseUtils import error_json_response, get_successful_response, get_unsuccessful_response

notificationRouter = APIRouter(prefix="/notifications", tags=["Notifications"])


@notificationRouter.get("", response_description="List notifications for the authenticated user")
def list_notifications(
    request: Request,
    groupselected: str = Header(None),
    callcenter: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    try:
        uid = require_authenticated_uid(request)
        assert_group_membership(uid, str(groupselected))
        items = notificationService.list_for_user(
            owner=uid,
            owner_group=str(groupselected),
            callcenter_only=callcenter,
            skip=skip,
            limit=limit,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(items)),
        )
    except Exception as exc:
        return error_json_response(exc)


@notificationRouter.patch("/{notification_id}/read", response_description="Mark one notification read")
def mark_notification_read(
    request: Request,
    notification_id: str,
    groupselected: str = Header(None),
):
    try:
        uid = require_authenticated_uid(request)
        assert_group_membership(uid, str(groupselected))
        updated = notificationService.mark_read(notification_id, uid)
        if not updated:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=get_unsuccessful_response("Notification not found"),
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response({"updated": True}),
        )
    except Exception as exc:
        return error_json_response(exc)


@notificationRouter.post("/mark-all-read", response_description="Mark all notifications read for user")
def mark_all_notifications_read(
    request: Request,
    body=Body(default={}),
    groupselected: str = Header(None),
):
    try:
        uid = require_authenticated_uid(request)
        assert_group_membership(uid, str(groupselected))
        callcenter = body.get("callcenter")
        callcenter_only = None if callcenter is None else bool(callcenter)
        updated = notificationService.mark_all_read(
            owner=uid,
            owner_group=str(groupselected),
            callcenter_only=callcenter_only,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response({"updated": updated}),
        )
    except Exception as exc:
        return error_json_response(exc)
