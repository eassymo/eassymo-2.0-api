from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, Request, status, Query, HTTPException
from app.schemas.Users import UserSchema
from app.utils import TypeUtilities as typeUtilities
from app.services import UserService as userService
from typing import Optional
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.dto.whatsapp_intake_dto import WhatsappIntakeConfirmDto, WhatsappIntakeStartDto
from app.services.WhatsappIntakeVerificationService import WhatsappIntakeVerificationService
from app.dependencies.group_auth import require_authenticated_uid, require_group_membership_from_header
from fastapi.encoders import jsonable_encoder

userRouter = APIRouter(prefix="/users")
whatsapp_intake_service = WhatsappIntakeVerificationService()


@userRouter.post("/create", response_description="User creation endpoint", response_model=UserSchema, tags=["Users"])
def create(request: Request, user: UserSchema = Body(...)):
    caller_uid = require_authenticated_uid(request)
    if str(user.uid) != str(caller_uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token uid must match user uid",
        )
    response = typeUtilities.parse_json(userService.create_user(user))
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)


@userRouter.get(
    "/me/whatsapp-intake/status",
    response_description="Verified POS WhatsApp status for current user",
    tags=["Users", "WhatsApp"],
)
def whatsapp_intake_status(request: Request):
    uid = require_authenticated_uid(request)
    body = whatsapp_intake_service.get_status(uid)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=get_successful_response(body),
    )


@userRouter.post(
    "/me/whatsapp-intake/start",
    response_description="Send WhatsApp template with confirm URL",
    tags=["Users", "WhatsApp"],
)
def whatsapp_intake_start(request: Request, payload: WhatsappIntakeStartDto = Body(...)):
    uid = require_authenticated_uid(request)
    body = whatsapp_intake_service.start(uid, payload.phone)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=get_successful_response(body),
    )


@userRouter.get(
    "/me/whatsapp-intake/pending/{token}",
    response_description="Preview pending WhatsApp verification",
    tags=["Users", "WhatsApp"],
)
def whatsapp_intake_preview(request: Request, token: str):
    uid = require_authenticated_uid(request)
    body = whatsapp_intake_service.preview(uid, token)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=get_successful_response(body),
    )


@userRouter.post(
    "/me/whatsapp-intake/confirm",
    response_description="Confirm WhatsApp link and save pos_whatsapp on user",
    tags=["Users", "WhatsApp"],
)
def whatsapp_intake_confirm(request: Request, payload: WhatsappIntakeConfirmDto = Body(...)):
    uid = require_authenticated_uid(request)
    require_group_membership_from_header(request)
    body = whatsapp_intake_service.confirm(uid, payload.token)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=get_successful_response(body),
    )


@userRouter.get("", response_description="users found", tags=["Users"])
def find(search_argument: Optional[str] = Query(None, title="search_argument")):
    try:
        filters = {}
        if search_argument != None:
            filters["search_argument"] = search_argument
        response = userService.find_users(filters)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))


@userRouter.get("/{uid}", response_description="User information endpoint", response_model=UserSchema, tags=["Users"])
def find(uid: str):
    response = typeUtilities.parse_json(userService.find_user(uid))
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)

@userRouter.put("/{uid}", response_description="Edit user", response_model=UserSchema, tags=["Users", "Edit"])
def update(uid: str, user:UserSchema = Body()):
    response = typeUtilities.parse_json(userService.update_user(uid, user))
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)


@userRouter.post("/add-role", response_model=UserSchema, tags=["Users"])
def add_role(request: Request, payload = Body(...)):
    try:
        caller_uid = require_authenticated_uid(request)
        if str(payload["user_uid"]) != str(caller_uid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify roles for another user",
            )
        response = userService.add_role_to_user(payload["user_uid"], payload["role_id"])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))


@userRouter.post("/remove-role", response_model=UserSchema, tags=["Users"])
def remove_role(request: Request, payload = Body(...)):
    try:
        caller_uid = require_authenticated_uid(request)
        if str(payload["user_uid"]) != str(caller_uid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify roles for another user",
            )
        response = userService.remove_role_from_user(payload["user_uid"], payload["role_id"])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))
