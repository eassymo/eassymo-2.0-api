from fastapi import APIRouter, Body, status, Query, Request, HTTPException
from app.schemas.Groups import GroupSchema
from typing import Optional
from app.services import GroupService as groupService
from fastapi.responses import JSONResponse
from typing import List, Dict, Any
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.dto.group_dto import EditGroupDto
from pymongo.errors import PyMongoError


groupRouter = APIRouter(prefix="/group")


@groupRouter.post("", response_description="", tags=["Groups"])
def create(
        user_id: Optional[str] = Query(
            None, title="user_id", description="user that will be added to the group references"),
        census_reference: Optional[str] = Query(
            None, title="census_reference", description="Census reference"),
        payload: GroupSchema = Body(...)):
    try:
        response = groupService.create_group(
            payload, census_reference, user_id)
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


@groupRouter.post("/users-from-group-ids-v2", response_description="", tags=["Groups"])
def find_users_from_group_v2(payload=Body(...)):
    try:
        response = groupService.find_users_by_groups_ids_v2(
            payload["group_ids"])
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
            content=get_unsuccessful_response(
                f"Group with id {group_id} not found")
        )


@groupRouter.get("", description="finds groups according to filters", tags=["partRequestInvite"])
def find(
    request: Request,
    search_argument: Optional[str] = Query(None, title="search_argument"),
    parent_request_id: Optional[str] = Query(None, title="parent_request_id"),
    is_callcenter: Optional[bool] = Query(None, title="is_callcenter")
):
    try:
        filters = {}
        groups_found: List[Dict[str, Any]] = []
        if search_argument != None:
            filters["search_argument"] = search_argument

        if parent_request_id != None:
            filters["parent_request_id"] = parent_request_id

        if is_callcenter != None:
            filters["is_callcenter"] = is_callcenter

        response = groupService.find(request, filters)

        for group_found in response:
            groups_found.append(group_found.toJson())

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(groups_found)))
    except (HTTPException, PyMongoError) as e:
        return JSONResponse(content=get_unsuccessful_response(e))


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


@groupRouter.post("/add-employee-to-group", tags=["Groups"])
def add_employee_to_group(payload=Body(...)):
    try:
        group_id: str = payload["group_id"]
        employee_uid: str = payload["employee_uid"]

        response = groupService.add_employee_to_group(group_id, employee_uid)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=get_unsuccessful_response(str(e))
        )


@groupRouter.get("/list-employees-from-group/{group_id}", tags=["Groups"])
def list_employees_from_groups(group_id: str):
    try:
        response = groupService.find_users_by_group_id(group_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=get_unsuccessful_response(str(e))
        )


@groupRouter.post("/transfer-ownership", tags=["Groups"])
def transfer_ownership(req: Request, payload=Body(...)):
    try:
        response = groupService.transfer_ownership(
            req, payload["group_id"], payload["new_owner"])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (PyMongoError, HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))


@groupRouter.post("/find-bulk", tags=["Groups"])
def find_bulk(req: Request, payload=Body(...)):
    try:
        response = groupService.find_bulk(payload["groups_ids"])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (PyMongoError, HTTPException) as e:
        return JSONResponse(status_code=e.status_code if hasattr(e, 'status_code') else status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(e))