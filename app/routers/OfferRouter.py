from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query
from app.schemas.Offer import Offer
from app.services import OfferService as offerService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder


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
        response = offerService.find_by_request_id_and_group(part_request_id, group_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))

@offerRouter.get("/build_filters/{propName}", description="Get the filter options for a specific prop name")
def build_filters(propName: str):
    try:
        response = offerService.build_filters(propName)
        return JSONResponse(status_code=status.HTTP_200_OK, content= get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
