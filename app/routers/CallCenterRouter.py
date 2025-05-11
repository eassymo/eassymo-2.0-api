from app.services import CallCenterService
from fastapi import APIRouter, Body, status, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.schemas.CallCenterConnection import CallCenterConnection

callCenterRouter = APIRouter(prefix="/callCenter")


@callCenterRouter.get("", description="Call center requests query", tags=["Call Center"])
def find(
    request: Request,
    search_term: Optional[str] = Query(None, title="search_term"),
    positions: Optional[List[str]] = Query(None, title="positions"),
    unitsOfMeasure: Optional[List[str]] = Query(None, title="unitsOfMeasure"),
    statuses: Optional[List[str]] = Query(None, title="statuses")
):
    try:

        filters = {}

        if search_term != None:
            filters["search_term"] = search_term

        if positions != None:
            filters["positions"] = positions

        if unitsOfMeasure != None:
            filters["unitsOfMeasure"] = unitsOfMeasure

        if statuses != None:
            filters["statuses"] = statuses

        groupSelected = request.state._state.get('groupSelected')
        response = CallCenterService.find(groupSelected, filters)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code, content=get_unsuccessful_response(e))


@callCenterRouter.post("/get_users_of_callcenters_from_group_ids", tags=["Call Center"])
def get_users_of_callcenters_from_group_ids(payload=Body()):
    try:
        group_ids = payload.get("group_ids")

        response = CallCenterService.get_users_of_callcenters_from_group_ids(
            group_ids)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content=get_unsuccessful_response(e))


@callCenterRouter.get("/get-related-groups/{callcenter_id}", description="gets groups that added the callcenter", tags=["Call Center"])
def get_related_groups(callcenter_id: str):
    try:
        response = CallCenterService.get_related_groups(callcenter_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content=get_unsuccessful_response(e))
