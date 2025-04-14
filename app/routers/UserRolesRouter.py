from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query, HTTPException
from app.schemas.UserRoles import UserRoles
from app.utils import TypeUtilities as typeUtilities
from app.services import UserRolesService as userRolesService
from typing import Optional
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder


userRolesRouter = APIRouter(prefix="/userRoles")


@userRolesRouter.post("", description="Insert a new user role", tags=["User Roles"])
def insert(payload: UserRoles = Body()):
    try:
        response = userRolesService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@userRolesRouter.get("", description="find user roles", tags=["User Roles"])
def find(
    user_id: Optional[str] = Query(None, title="user_uid"),
    role: Optional[str] = Query(None, title="role"),
    group: Optional[str] = Query(None, title="group"),
    active: Optional[bool] = Query(None, title="active")
):
    try:
        filters = {}

        if user_id != None:
            filters["user_uid"] = user_id
        if role != None:
            filters["role"] = role
        if group != None:
            filters["group"] = group
        if active != None:
            filters["active"] = active

        response = userRolesService.find(filters)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@userRolesRouter.post("/activate-role", description="Activate the user role", tags=["User Roles"])
def activate_role(
        payload=Body(...)
):
    try:
        user_uid = payload["user_uid"]
        role = payload["role"]
        new_group_id = payload["new_group_id"]

        response = userRolesService.activate_role(user_uid, role, new_group_id)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@userRolesRouter.post("/add-role-to-user", description="Adds an active role to a user for a group", tags=["User Roles"])
def add_role_to_user(
    payload=Body(...)
):
    try:
        user_uid = payload["user_uid"]
        role = payload["role"]
        group = payload["group"]

        response = userRolesService.add_role_to_user(user_uid, role, group)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@userRolesRouter.post("/delete-role-from-user", description="deletes a given role for a user", tags=["User Roles"])
def remove(
    payload=Body(...)
):
    try:
        user_uid = payload["user_uid"]
        role = payload["role"]
        group = payload["group"]

        response = userRolesService.remove_role_from_user(
            user_uid, role, group)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(content=get_unsuccessful_response(e))
