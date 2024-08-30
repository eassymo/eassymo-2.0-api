from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query
from app.schemas.Offer import Offer
from app.services import OfferService as offerService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder
from typing import List

offerRouter = APIRouter(prefix="/offer")


@offerRouter.post("", description="Creation of an offer for a request")
def insert(payload: Offer = Body(...)):
    try:
        response = offerService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@offerRouter.get("/find_by_request_id_and_group", description="Get a specific offer for a request")
def find_by_id(part_request_id: str = Query(None, title="part_request_id",
                                            description="The id of the offer"),
               group_id: str = Query(None, title="group_id",
                                     description="The id of the group")):
    try:
        response = offerService.find_by_request_id_and_group(
            part_request_id, group_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@offerRouter.get("/build-filters", description="Get the filter options for a specific prop name")
def build_filters(
    prop_name: str = Query(None, title="prop_name")
):
    try:
        response = offerService.build_filters(prop_name)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@offerRouter.get("", description="General offer get service")
def find(
    car_models: str = Query(None, title="car_models"),
    group_ids: str = Query(None, title="group_ids")
):
    try:
        response = offerService.find_specific(car_models, group_ids)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@offerRouter.get("/offers-by-groups/{request_id}", description="Get offers by groups")
def get_offers_by_groups(request_id: str):
    try:
        response = offerService.find_request_offers_by_groups(request_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))