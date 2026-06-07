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
        return JSONResponse(content=get_unsuccessful_response(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@groupCarRouter.get("", tags=["GroupVehicle"])
def find(
    group_id: Optional[str] = Query(None, title="user_id",
                                    description="user that will be added to the group references")
):
    try:
        response = typeUtilities.parse_json(
            GroupCarService.find_by_group(group_id))
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@groupCarRouter.get("/{id}", tags=["GroupVehicle"])
def find_by_id(
    id: str
):
    try:
        response = typeUtilities.parse_json(
            GroupCarService.find_by_id(id)
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

@groupCarRouter.put("/{id}", tags=["GroupVehicle"])
def update(
    id: str,
    payload: GroupVehicle = Body(description="")
):
    try:
        response = typeUtilities.parse_json(
            GroupCarService.edit(id, payload)
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)



@groupCarRouter.delete("/{id}", tags=["GroupVehicle"])
def delete(id: str):
    try:
        response = GroupCarService.remove(id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)