from typing import Optional
from fastapi import APIRouter, Body, Query, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.schemas.RequestStatusByGroup import RequestStatusByGroup
from app.services import RequestStatusByGroupService
from app.utils.ResponseUtils import get_successful_response

requestStatusByGroupRouter = APIRouter(prefix="/requestStatusByGroup")


@requestStatusByGroupRouter.post("", response_model=RequestStatusByGroup)
def insert(payload: RequestStatusByGroup = Body(None)):
    response = RequestStatusByGroupService.insert(payload)
    return JSONResponse(status_code=status.HTTP_200_OK, content=response.toJson())


@requestStatusByGroupRouter.get("/", response_model=RequestStatusByGroup)
def find_by_group_and_request_id(
    group_id: Optional[str] = Query(None, title="group_id"),
    request_id: Optional[str] = Query(None, title="request_id")
):
    response = RequestStatusByGroupService.find_by_group_and_request_id(group_id, request_id)

    if response:
        response = response.toJson()

    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))


@requestStatusByGroupRouter.put("/{id}", response_model=RequestStatusByGroup)
def update(id: str, payload: RequestStatusByGroup = Body(None)):
    response = RequestStatusByGroupService.update(id, payload)

    if response:
        response = response.toJson()

    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))


@requestStatusByGroupRouter.delete("/{id}", response_model=bool)
def delete(id: str):
    response = RequestStatusByGroupService.delete(id)

    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
