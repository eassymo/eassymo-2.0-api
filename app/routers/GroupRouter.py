from fastapi import APIRouter, Body, status, Query
from app.schemas.Groups import GroupSchema
from typing import Optional
from app.services import GroupService as groupService
from fastapi.responses import JSONResponse
from typing import List
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

groupRouter = APIRouter(prefix="/group")


@groupRouter.post("", response_description="", tags=["Groups"])
def create(
    user_id: Optional[str] = Query(None, title="user_id", description="user that will be added to the group references"),
    census_reference: Optional[str] = Query(None, title="census_reference", description="Census reference"),
           payload: GroupSchema = Body(...)):
    response = groupService.create_group(payload, census_reference, user_id)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)


@groupRouter.post("/users-from-group-ids", response_description="", tags=["Groups"])
def find_users_from_group(payload: List[str] = Body(...)):
    response = groupService.find_users_by_groups_ids(payload)
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))