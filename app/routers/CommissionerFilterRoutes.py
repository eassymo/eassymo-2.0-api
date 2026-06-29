from fastapi import APIRouter, Body, status, Query

from app.services import CommissionerFiltersService as commissionerFilterService
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

commisionerFilterRouter = APIRouter(prefix="/commissioner-filters")

@commisionerFilterRouter.get("/{commissioner_id}", tags=["Commissioner Filters"])
def build_filters(commissioner_id: str):
    try:
        response = commissionerFilterService.build_commissioner_offer_filters(commissioner_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))