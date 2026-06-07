from app.services import CallCenterManagementListService
from fastapi import APIRouter, status, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from typing import Optional, Any
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.schemas.CallCenterManagementList import CallCenterManagementList

callCenterManagementListRouter = APIRouter(prefix="/callCenterManagementList")


@callCenterManagementListRouter.post("", tags=["Call Center Management List"])
def insert(payload: Any = Body(...)):
    try:
        response = CallCenterManagementListService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))

    except (HTTPException, Exception) as e:
        return JSONResponse(content=get_unsuccessful_response(e))
    

@callCenterManagementListRouter.get("", tags=["Call Center Management List"])
def find(
    callcenter_id: Optional[str] = Query(None, title="callcenter_id"),
    user_id: Optional[str] = Query(None, title="user_id")
):
    try:

        filters = {
            "active": True
        }

        if callcenter_id != None:
            filters["callcenter_id"] = callcenter_id

        if user_id != None:
            filters["user_id"] = user_id

        response = CallCenterManagementListService.find(filters)
        
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))

    except (HTTPException, Exception) as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@callCenterManagementListRouter.get("/{id}", tags=["Call Center Management List"])
def find_by_id(id: str):
    try:
        response = CallCenterManagementListService.find_by_id(id)
        
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))

    except (HTTPException, Exception) as e:
        return JSONResponse(content=get_unsuccessful_response(e))