from fastapi import APIRouter, status, Query, Depends, HTTPException, Request
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
    params: Params = Depends(),
    id: Optional[str] = Query(None, title="id", description="Census id"),
    exclude_group: Optional[str] = Query(None, title="exclude_group"),
    group_id: Optional[str] = Query(None, title="group_id"),
    userUid: Optional[str] = Query(
        None, title="userUid", description="User uid"),
    search_argument: Optional[str] = Query(None, title="search_argument", description="search argument used for the $text index"),
    show_only_census: Optional[bool] = Query(
        None, title="show_only_census", description="Show only census"),
    Entity_Type: Optional[str] = Query(None, title="Entity_Type")
):
    parameters = {
        "id": id,
        "userUid": userUid,
        "group_id": group_id,
        "Entity_Type": Entity_Type,
        "exclude_group": exclude_group,
        "search_argument": search_argument,
        "show_only_census": show_only_census,
        "limit": params.dict()["size"],
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
