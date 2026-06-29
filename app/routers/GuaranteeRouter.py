from fastapi.responses import JSONResponse
from fastapi import APIRouter, status, Query
from app.schemas.Guarantee import Guarantee
from typing import Optional
from app.services import GuaranteeService as guaranteeService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder


guaranteeRouter = APIRouter(prefix="/guarantee")


@guaranteeRouter.post("", description="insert a new guarantee")
def insert(payload: Guarantee):
    try:
        response = guaranteeService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@guaranteeRouter.get("", description="search guarantee by label")
def find(search_param: Optional[str] = Query(title="search_param")):
    try:
        response = guaranteeService.find_guarantee_by_label(search_param)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
