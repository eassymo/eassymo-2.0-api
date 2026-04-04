from fastapi import APIRouter, Body, Header, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.services import PendingCartService as pendingCartService
from app.schemas.PendingCart import SavePendingCartRequest
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

pendingCartRouter = APIRouter(prefix="/pending-cart")


@pendingCartRouter.put(
    "/",
    response_description="Upsert pending cart",
    tags=["PendingCart"],
)
def save_pending_cart(body: SavePendingCartRequest = Body(...)):
    try:
        part_list = [p.dict() for p in body.part_list]
        response = pendingCartService.save(body.user_uid, body.group_id, body.vehicle_id, part_list)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@pendingCartRouter.get(
    "/{user_uid}",
    response_description="Get pending cart for user",
    tags=["PendingCart"],
)
def get_pending_cart(user_uid: str, groupselected: str = Header(None)):
    try:
        response = pendingCartService.get(user_uid, groupselected)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@pendingCartRouter.delete(
    "/{user_uid}",
    response_description="Clear pending cart for user",
    tags=["PendingCart"],
)
def delete_pending_cart(user_uid: str, groupselected: str = Header(None)):
    try:
        response = pendingCartService.delete(user_uid, groupselected)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
