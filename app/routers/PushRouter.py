from fastapi import APIRouter, Body, Request, status
from fastapi.responses import JSONResponse

from app.dependencies.group_auth import require_authenticated_uid
from app.repositories import PushSubscriptionRepository as pushSubscriptionRepository
from app.schemas.PushSubscription import (
    PushDispatchRequest,
    PushSubscriptionCreate,
    PushSubscriptionDelete,
)
from app.services import push_service
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

pushRouter = APIRouter(prefix="/push", tags=["Push"])


@pushRouter.post("/subscriptions", description="Register or update an FCM web push token")
def register_subscription(request: Request, payload: PushSubscriptionCreate = Body(...)):
    try:
        uid = require_authenticated_uid(request)
        pushSubscriptionRepository.upsert_subscription(
            uid=uid,
            token=payload.token.strip(),
            user_agent=payload.userAgent,
            group_id=payload.groupId,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response({"registered": True}),
        )
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content=get_unsuccessful_response(exc.detail))
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=get_unsuccessful_response(exc),
        )


@pushRouter.delete("/subscriptions", description="Remove FCM web push token(s) for the current user")
def delete_subscription(request: Request, payload: PushSubscriptionDelete = Body(default=PushSubscriptionDelete())):
    try:
        uid = require_authenticated_uid(request)
        deleted = pushSubscriptionRepository.delete_subscription(uid, payload.token)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response({"deleted": deleted}),
        )
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content=get_unsuccessful_response(exc.detail))
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=get_unsuccessful_response(exc),
        )


@pushRouter.post("/dispatch", description="Send a web push for a notification payload")
def dispatch_push(request: Request, payload: PushDispatchRequest = Body(...)):
    try:
        require_authenticated_uid(request)
        sent = push_service.send_push_from_notification(payload.model_dump())
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response({"sent": sent}),
        )
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content=get_unsuccessful_response(exc.detail))
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=get_unsuccessful_response(exc),
        )
