from fastapi import APIRouter, Body, status, Query
from app.schemas.Groups import GroupSchema
from typing import Optional
from app.services import GroupService as groupService
from fastapi.responses import JSONResponse

groupRouter = APIRouter(prefix="/group")


@groupRouter.post("", response_description="", tags=["Groups"])
def create(
    user_id: Optional[str] = Query(None, title="user_id", description="user that will be added to the group references"),
    census_reference: Optional[str] = Query(None, title="census_reference", description="Census reference"),
           payload: GroupSchema = Body(...)):
    response = groupService.create_group(payload, census_reference, user_id)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response)


""" @groupRouter.get("/find-by-user/{userUid}", response_description="Groups that are linked to this user", tags=["Groups"])
def find_by_user(userUid: str):
     """