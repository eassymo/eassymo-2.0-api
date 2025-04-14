from app.services import CallCenterService
from fastapi import APIRouter, Body, status, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.schemas.CallCenterConnection import CallCenterConnection

callCenterRouter = APIRouter(prefix="/callCenter")


@callCenterRouter.get("", description="Call center requests query", tags=["Call Center"])
def find(request: Request, search_term: Optional[str] = Query(None, title="search_term")):
    try:

        filters = {}
        
        if search_term != None:
            filters["search_term"] = search_term

        groupSelected = request.state._state.get('groupSelected')
        response = CallCenterService.find(groupSelected, filters)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except (HTTPException) as e:
        return JSONResponse(status_code=e.status_code, content=get_unsuccessful_response(e))
