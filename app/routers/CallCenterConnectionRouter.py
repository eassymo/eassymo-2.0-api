from app.services import CallCenterConnectionService
from fastapi import APIRouter, Body, status, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.schemas.CallCenterConnection import CallCenterConnection

callCenterConnectionRouter = APIRouter(prefix="/callCenterConnection")


@callCenterConnectionRouter.post("", description="creates a unique connection between a call center and a group", tags=["Call Center"])
def insert(payload: CallCenterConnection = Body()):
    try:
        response = CallCenterConnectionService.insert(payload)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code, content=get_unsuccessful_response(e))


@callCenterConnectionRouter.get("", description="query service for call center connections", tags=["Call Center"])
def find_one(
    callcenter_id: Optional[str] = Query(default=None, title="callcenter_id"),
    group_id: Optional[str] = Query(default=None, title="group_id")
):
    try:
        filters = {}

        if callcenter_id != None:
            filters["callcenter_id"] = callcenter_id

        if group_id != None:
            filters["group_id"] = group_id

        response = CallCenterConnectionService.find_one(filters)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code, content=get_unsuccessful_response(e))


@callCenterConnectionRouter.delete("/{id}", description="delete service", tags=["Call Center"])
def delete(id: str):
    try: 
        response = CallCenterConnectionService.delete(id)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code, content=get_unsuccessful_response(e))