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
    group_id: Optional[str] = Query(None, title="group_id", description=""),
    group_role: Optional[str] = Query(
        None, title="group_role", description="current logged in role"),
    search_argument: Optional[str] = Query(None, title="search_argument"),
    creator_group: Optional[str] = Query(
        None, title="creator_group"),
    vehicle_model: Optional[str] = Query(
        None, title="vehicle_model"),
    created_at: Optional[str] = Query(
        None, title="created_at"),
):
    try:
        part_requests = partRequestService.find_grouped(
            group_id,
            group_role,
            creator_group,
            vehicle_model,
            created_at,
            search_argument,
        )
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
def search(
    search_argument: Optional[str] = Query(None, title="search_argument"),
    category: Optional[str] = Query(None, title="category"),
    sub_category: Optional[str] = Query(None, title="sub_category"),
    part_type: Optional[str] = Query(None, title="part_type")
):
    try:
        reduced_part_requests = partRequestService.sexarch(
            search_argument, category, sub_category, part_type)

        reduced_part_requests = __format_reduced_parts(reduced_part_requests)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(reduced_part_requests))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


def __format_reduced_parts(part_requests):
    formatted_part_requests = []
    for part in part_requests:
        part = {
            **part,
            "group_info": {
                **part["group_info"],
                "_id": str(part["group_info"]["_id"])
            }
        }
        formatted_part_requests.append(part)
    return formatted_part_requests


@partRequestRouter.get("/filter/build-filter", response_description="available values for the provided propName")
def build_filter(prop_name: Optional[str] = Query(None, title="prop_name")):
    try:
        filter_options = partRequestService.build_filter(prop_name)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(filter_options))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@partRequestRouter.get("/sibling-requests-with-offers/{parent_request_uid}", response_description="part request with offers")
def find_sibling_requests_with_offers(
    parent_request_uid: str,
    offer_owner_group: Optional[str] = Query(None, title="offer_owner_group")
):
    try:
        part_requests_with_offers = partRequestService.find_sibling_requests_with_offers(
            parent_request_uid, offer_owner_group)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(part_requests_with_offers))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
