from fastapi import APIRouter, status, Query, Depends
from typing import List, Optional
from app.utils import TypeUtilities as typeUtilities
from app.services import CensusService as censusService
from fastapi.responses import JSONResponse
from app.schemas.Census import CensusSchema
from fastapi_pagination import Params, paginate


censusRouter = APIRouter(prefix="/census")


@censusRouter.get("", response_description="Service for listing the census items", response_model=List[CensusSchema], tags=["Census", "list"])
def find(
    params: Params = Depends(),
    userUid: Optional[str] = Query(
        None, title="userUid", description="User uid"),
    Entity_Name: Optional[str] = Query(
        None, title="Entity_Name", description="Entity name in collection"),
    Entity_Address_City: Optional[str] = Query(
        None, title="Entity_Address_City", description="City of entity"),
    Entity_Location_State: Optional[str] = Query(
        None, title="Entity_Location_State", description="State of entity"),
    show_only_census: Optional[bool] = Query(
        None, title="show_only_census", description="Show only census")
):
    parameters = {
        "userUid": userUid,
        "Entity_Name": Entity_Name,
        "Entity_Address_City": Entity_Address_City,
        "Entity_Location_State": Entity_Location_State,
        "show_only_census": show_only_census,
        "limit": params.dict()["size"],
        "page":  params.dict()["page"]
    }
    census_items = typeUtilities.parse_json(censusService.find(parameters))

    return JSONResponse(status_code=status.HTTP_200_OK, content=census_items)


@censusRouter.get("/states", response_description="", response_model=List[str], tags=["Census"])
def get_states():
    response = typeUtilities.parse_json(censusService.get_states())
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)


@censusRouter.get("/cities", response_description="", response_model=List[str], tags=["Census", "Cities"])
def get_cities(state: Optional[str] = Query(None, title="state", description="used to filter cities based on state selected")):
    response = typeUtilities.parse_json(censusService.get_cities(state))
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)
