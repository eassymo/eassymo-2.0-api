from typing import Optional
from fastapi import APIRouter, Body, Query, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.schemas.OfferStatusByGroup import OfferStatusByGroup
from app.repositories import OfferStatusByGroupRepository
from app.utils.ResponseUtils import get_successful_response

offerStatusByGroupRouter = APIRouter(prefix="/offerStatusByGroup")


@offerStatusByGroupRouter.post("", response_model=OfferStatusByGroup)
def insert(payload: OfferStatusByGroup = Body(None)):
    response = OfferStatusByGroupRepository.insert(payload)
    return JSONResponse(status_code=status.HTTP_200_OK, content=response.toJson())


@offerStatusByGroupRouter.get("/", response_model=OfferStatusByGroup)
def find_by_group_and_offer_id(
    group_id: Optional[str] = Query(None, title="group_id"),
    offer_id: Optional[str] = Query(None, title="offer_id")
):
    response = OfferStatusByGroupRepository.find_by_group_and_offer_id(group_id, offer_id)

    if response:
        response = response.toJson()

    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))


@offerStatusByGroupRouter.put("/{id}", response_model=OfferStatusByGroup)
def update(id: str, payload: OfferStatusByGroup = Body(None)):
    response = OfferStatusByGroupRepository.update(id, payload)

    if response:
        response = response.toJson()

    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
