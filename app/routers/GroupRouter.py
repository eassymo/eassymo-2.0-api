from fastapi import APIRouter, Body, status, Query, Request
from app.schemas.Groups import GroupSchema
from typing import Optional
from app.services import GroupService as groupService
from fastapi.responses import JSONResponse
from typing import List
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.dto.group_dto import EditGroupDto


groupRouter = APIRouter(prefix="/group")


@groupRouter.post("", response_description="", tags=["Groups"])
def create(
        user_id: Optional[str] = Query(
            None, title="user_id", description="user that will be added to the group references"),
        census_reference: Optional[str] = Query(
            None, title="census_reference", description="Census reference"),
        payload: GroupSchema = Body(...)):
    try:
        response = groupService.create_group(payload, census_reference, user_id)
        return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=get_unsuccessful_response(str(e))
        )


@groupRouter.post("/users-from-group-ids", response_description="", tags=["Groups"])
def find_users_from_group(payload: List[str] = Body(...)):
    try:
        response = groupService.find_users_by_groups_ids(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=get_unsuccessful_response(str(e))
        )


@groupRouter.get("/{group_id}", tags=["Groups"])
def get_by_id(group_id: str):
    try:
        response = groupService.find_group_by_id(group_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=get_unsuccessful_response(f"Group with id {group_id} not found")
        )


@groupRouter.put("/{group_id}", tags=["Groups"])
def edit_group(request: Request, group_id: str, payload: EditGroupDto = Body(...)):
    try:
        user_info = request.state._state.get('user')
        response = groupService.edit_group_by_id(
            user_info.get('uid'), group_id, payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=get_unsuccessful_response(str(e))
        )