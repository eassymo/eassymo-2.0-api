from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query, HTTPException
from app.schemas.Users import UserSchema
from app.utils import TypeUtilities as typeUtilities
from app.services import UserService as userService
from typing import Optional
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder


userRouter = APIRouter(prefix="/users")

@userRouter.post("/create", response_description="User creation endpoint", response_model=UserSchema, tags=["Users"])
def create(user: UserSchema = Body(...)):
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
def add_role(payload = Body(...)):
    try:
        response = userService.add_role_to_user(payload["user_uid"], payload["role_id"])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))


@userRouter.post("/remove-role", response_model=UserSchema, tags=["Users"])
def add_role(payload = Body(...)):
    try:
        response = userService.remove_role_from_user(payload["user_uid"], payload["role_id"])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))
