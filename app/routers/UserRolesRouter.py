from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, Request, status, Query, HTTPException
from app.schemas.UserRoles import UserRoles
from app.services import UserRolesService as userRolesService
from typing import Optional
from app.utils.ResponseUtils import get_successful_response, error_json_response
from app.dependencies.group_auth import authorize_role_mutation
from fastapi.encoders import jsonable_encoder


userRolesRouter = APIRouter(prefix="/userRoles")


@userRolesRouter.post("", description="Insert a new user role", tags=["User Roles"])
def insert(request: Request, payload: UserRoles = Body()):
    try:
        authorize_role_mutation(request, payload.user_uid, payload.group)
        response = userRolesService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return error_json_response(e)


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
        return error_json_response(e)


@userRolesRouter.post("/activate-role", description="Activate the user role", tags=["User Roles"])
def activate_role(request: Request, payload=Body(...)):
    try:
        user_uid = payload["user_uid"]
        role = payload["role"]
        new_group_id = payload["new_group_id"]

        authorize_role_mutation(request, user_uid, new_group_id)

        response = userRolesService.activate_role(user_uid, role, new_group_id)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return error_json_response(e)


@userRolesRouter.post("/add-role-to-user", description="Adds an active role to a user for a group", tags=["User Roles"])
def add_role_to_user(request: Request, payload=Body(...)):
    try:
        user_uid = payload["user_uid"]
        role = payload["role"]
        group = payload["group"]

        authorize_role_mutation(request, user_uid, group)

        response = userRolesService.add_role_to_user(user_uid, role, group)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return error_json_response(e)


@userRolesRouter.post("/delete-role-from-user", description="deletes a given role for a user", tags=["User Roles"])
def remove(request: Request, payload=Body(...)):
    try:
        user_uid = payload["user_uid"]
        role = payload["role"]
        group = payload["group"]

        authorize_role_mutation(request, user_uid, group)

        response = userRolesService.remove_role_from_user(
            user_uid, role, group)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return error_json_response(e)
