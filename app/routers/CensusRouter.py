from fastapi import APIRouter, status, Query, Depends, HTTPException, Request, Body
from typing import List, Optional
from app.utils import TypeUtilities as typeUtilities
from app.services import CensusService as censusService
from fastapi.responses import JSONResponse
from app.schemas.Census import CensusSchema
from fastapi_pagination import Params
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder


censusRouter = APIRouter(prefix="/census")


@censusRouter.get("", response_description="Service for listing the census items", response_model=List[CensusSchema], tags=["Census", "list"])
def find(
    request: Request,
    params: Params = Depends(),
    id: Optional[str] = Query(None, title="id", description="Census id"),
    exclude_group: Optional[str] = Query(None, title="exclude_group"),
    group_id: Optional[str] = Query(None, title="group_id"),
    userUid: Optional[str] = Query(
        None, title="userUid", description="User uid"),
    search_argument: Optional[str] = Query(
        None, title="search_argument", description="search argument used for the $text index"),
    show_only_census: Optional[bool] = Query(
        None, title="show_only_census", description="Show only census"),
    Entity_Type: Optional[str] = Query(None, title="Entity_Type"),
    Entity_Location_State: Optional[str] = Query(
        None, title="Entity_Location_State"),
    Entity_Address_City: Optional[str] = Query(
        None, title="Entity_Address_City"),
    lat: Optional[float] = Query(
        None, title="lat", description="Latitude for geospatial search"),
    lng: Optional[float] = Query(
        None, title="lng", description="Longitude for geospatial search"),
    range_km: Optional[float] = Query(
        None, title="range_km", description="Search radius in kilometers"),
    limit: Optional[int] = Query(50, title="limit")
):
    user = request.state._state.get('user')
    groupSelected = request.state._state.get('groupSelected')

    parameters = {
        "id": id,
        "userUid": userUid if userUid != None and len(userUid) > 0 else user.get("uid"),
        "group_id": group_id if group_id != None and len(group_id) > 0 else groupSelected,
        "Entity_Type": Entity_Type,
        "exclude_group": exclude_group,
        "search_argument": search_argument,
        "show_only_census": show_only_census,
        "Entity_Location_State": Entity_Location_State,
        "Entity_Address_City": Entity_Address_City,
        "lat": lat,
        "lng": lng,
        "range_km": range_km,
        "limit": limit,
        "page":  params.dict()["page"]
    }
    census_items = typeUtilities.parse_json(censusService.find(parameters))

    return JSONResponse(status_code=status.HTTP_200_OK, content=census_items)


@censusRouter.get("/text-search/{search_argument}", tags=["Census"])
def text_search(request: Request, search_argument: str, parent_request_id: Optional[str] = Query(None, title="parent_request_id")):
    try:
        response = typeUtilities.parse_json(
            censusService.text_search(request, search_argument, parent_request_id))
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))

    except (HTTPException, Exception) as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@censusRouter.get("/states", response_description="", response_model=List[str], tags=["Census"])
def get_states():
    response = typeUtilities.parse_json(censusService.get_states())
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)


@censusRouter.get("/cities", response_description="", response_model=List[str], tags=["Census", "Cities"])
def get_cities(state: Optional[str] = Query(None, title="state", description="used to filter cities based on state selected")):
    response = typeUtilities.parse_json(censusService.get_cities(state))
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)


@censusRouter.post("/verify-for-similitudes", response_description="", tags=["Census"])
def verify_by_similitudes(
    payload=Body(...)
):
    try:
        response = censusService.verify_for_similitudes(payload["lat"], payload["lng"], payload["name"], payload["range_meters"])

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(content=get_unsuccessful_response(e))
