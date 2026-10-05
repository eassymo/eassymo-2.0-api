from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, Request, status, Query, HTTPException
from pydantic import BaseModel
from app.schemas.Users import UserSchema
from app.utils import TypeUtilities as typeUtilities
from app.services import UserService as userService
from app.services.WhatsappIntakeVerificationService import WhatsappIntakeVerificationService
from typing import Optional
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.dependencies.group_auth import require_authenticated_uid
from fastapi.encoders import jsonable_encoder


userRouter = APIRouter(prefix="/users")


class WhatsappIntakeStartRequest(BaseModel):
    phone: str


class WhatsappIntakeConfirmRequest(BaseModel):
    token: str


@userRouter.get("/me/whatsapp-intake/status", tags=["Users"])
def whatsapp_intake_status(request: Request):
    uid = require_authenticated_uid(request)
    result = WhatsappIntakeVerificationService().get_status(uid)
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))


@userRouter.post("/me/whatsapp-intake/start", tags=["Users"])
def whatsapp_intake_start(request: Request, payload: WhatsappIntakeStartRequest = Body(...)):
    uid = require_authenticated_uid(request)
    result = WhatsappIntakeVerificationService().start(uid, payload.phone)
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))


@userRouter.get("/me/whatsapp-intake/pending/{token}", tags=["Users"])
def whatsapp_intake_preview(request: Request, token: str):
    uid = require_authenticated_uid(request)
    result = WhatsappIntakeVerificationService().preview(uid, token)
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))


@userRouter.post("/me/whatsapp-intake/confirm", tags=["Users"])
def whatsapp_intake_confirm(request: Request, payload: WhatsappIntakeConfirmRequest = Body(...)):
    uid = require_authenticated_uid(request)
    result = WhatsappIntakeVerificationService().confirm(uid, payload.token)
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))

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
