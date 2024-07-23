from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query
from app.services import PartRequestService as partRequestService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.schemas.PartRequest import PartRequest
from fastapi.encoders import jsonable_encoder
from typing import Optional


partRequestRouter = APIRouter(prefix="/partRequest")


@partRequestRouter.post("", response_description="Created id of the part request", tags=["PartRequest"])
def create(payload: PartRequest):
    try:
        response = partRequestService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@partRequestRouter.get("", response_description="Will return the list of part requests using the user uid and group uid")
def find(
    user_uid: Optional[str] = Query(
        None, title="user_uid", description="User uid"),
    group_id: Optional[str] = Query(
        None, title="group_id", description="Group id"),
):
    try:
        response = partRequestService.find(user_uid, group_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@partRequestRouter.get("/grouped", response_description="part requests grouped by group")
def find_grouped(
    group_id: Optional[str] = Query(None, title="group_id", description="")
):
    try:
        part_requests = partRequestService.find_grouped(group_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(part_requests))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@partRequestRouter.get("/{id}", response_description="Will return the specific part response")
def find_by_id(id: str):
    try:
        response = partRequestService.find_by_id(id)
        response = {
            **response,
            "createdAt": str(response["createdAt"]),
            "updatedAt": str(response["updatedAt"])
        }
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@partRequestRouter.get("/search/reduced", response_description="Will return the reduced description")
def search(search_argument: Optional[str] = Query(None, title="search_argument")):
    try:
        reduced_part_requests = partRequestService.search(search_argument)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(reduced_part_requests))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
