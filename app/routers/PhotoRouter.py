from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder

from typing import Annotated, List
from fastapi import UploadFile, Form
from app.services import UploadPictureService as uploadPictureService


photoRouter = APIRouter(prefix="/photo")


@photoRouter.post("/", response_description="Upload photo", tags=["Photos"])
async def upload_photo(files: Annotated[List[UploadFile], Form()], userId: Annotated[str, Form()]):
    response = await uploadPictureService.upload_user_photos(files, userId)
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)
