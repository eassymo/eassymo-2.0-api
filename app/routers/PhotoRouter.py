from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, Request, status, Query
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from fastapi.encoders import jsonable_encoder

from typing import Annotated, List
from fastapi import UploadFile, Form
from app.services import UploadPictureService as uploadPictureService
from app.repositories import GuestDeliveryProfileRepository as guestProfileRepository
from app.repositories import OrderRepository as orderRepository
from app.schemas.GuestDeliveryProfile import GuestDeliveryProfileStatus


photoRouter = APIRouter(prefix="/photo")


@photoRouter.post("/", response_description="Upload photo", tags=["Photos"])
async def upload_photo(files: Annotated[List[UploadFile], Form()], userId: Annotated[str, Form()]):
    response = await uploadPictureService.upload_user_photos(files, userId)
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)


@photoRouter.post("/guest", response_description="Upload photo for guest delivery", tags=["Photos"])
async def upload_guest_photo(request: Request, files: Annotated[List[UploadFile], Form()]):
    guest_token = request.headers.get("X-Guest-Token")
    if not guest_token:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=get_unsuccessful_response("Missing X-Guest-Token header"),
        )

    profile_doc = guestProfileRepository.find_by_token(guest_token)
    if not profile_doc or profile_doc.get("status") != GuestDeliveryProfileStatus.ACTIVE:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=get_unsuccessful_response("Unrecognised or inactive guest token"),
        )

    active_order = orderRepository.find_one({
        "delivery_assignment.guest_token": guest_token,
        "status": {"$nin": ["CANCELED", "RECIEVED"]},
    })
    if not active_order:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=get_unsuccessful_response("No active order found for this guest token"),
        )

    response = await uploadPictureService.upload_guest_photos(files, guest_token)
    return JSONResponse(status_code=status.HTTP_200_OK, content=response)
