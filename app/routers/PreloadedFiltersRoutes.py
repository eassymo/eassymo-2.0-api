from typing import List, Optional
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, Query, status
from app.schemas.PreloadedFilters import PreloadedFilters
from app.services import PreloadedFiltersService as preloadedFilterService
from app.utils import TypeUtilities
from app.utils.ResponseUtils import get_successful_response

preloadedFiltersRouter = APIRouter(prefix="/preloadedFilters")


@preloadedFiltersRouter.post("", response_description="Inserted preloaded filter", response_model=PreloadedFilters)
def insert(payload: PreloadedFilters = Body(None)):
    response = preloadedFilterService.insert(payload)
    return JSONResponse(status_code=status.HTTP_200_OK, content=response.toJson())


@preloadedFiltersRouter.get("/", response_description="List of preloaded filters", response_model=PreloadedFilters, tags=["Preloaded Filters"])
def find_by_user_group_type(
    user_uid: Optional[str] = Query(None, title="user_uid"),
    group_id: Optional[str] = Query(None, title="group_id"),
    filter_type: Optional[str] = Query(None, title="filter_type")
):

    response = preloadedFilterService.find_by_user_group_type(
        user_uid=user_uid,
        group_id=group_id,
        type=filter_type
    )

    if response:
        response = response.toJson()

    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))


@preloadedFiltersRouter.delete("/{id}", response_model=bool, tags=["Preloaded Filters"])
def delete(id: str):
    response = preloadedFilterService.delete(id)

    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
