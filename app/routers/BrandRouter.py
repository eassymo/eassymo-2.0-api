from fastapi.responses import JSONResponse
from fastapi import APIRouter, status, Query
from typing import Optional
from app.services import BrandService as brandService
from app.schemas.Brand import Brand
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder


brandRouter = APIRouter(prefix="/brand")


@brandRouter.post("", description="insert a new brand")
def insert(payload: Brand):
    try:
        response = brandService.insert(payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@brandRouter.get("", description="search for a brand by label")
def find(search_param: Optional[str] = Query(title="search_param")):
    try:
        response = brandService.find_brand_by_label(search_param)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
