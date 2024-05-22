from fastapi import APIRouter, status, Query, Body
from app.schemas.GroupVehicle import GroupVehicle
from app.services import GroupCarService
from fastapi.responses import JSONResponse
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder
from typing import Optional
from app.utils import TypeUtilities as typeUtilities


groupCarRouter = APIRouter(prefix="/groupVehicle")


@groupCarRouter.post("", tags=["GroupVehicle"])
def insert(
    payload: GroupVehicle = Body(description="")
):
    try:
        response = GroupCarService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@groupCarRouter.get("", tags=["GroupVehicle"])
def find(
    group_id: Optional[str] = Query(None, title="user_id",
                                    description="user that will be added to the group references")
):
    response = typeUtilities.parse_json(
        GroupCarService.find_by_group(group_id))
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))


@groupCarRouter.get("/{id}", tags=["GroupVehicle"])
def find_by_id(
    id: str
):
    response = typeUtilities.parse_json(
        GroupCarService.find_by_id(id)
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
