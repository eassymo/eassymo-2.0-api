from fastapi import APIRouter, Body, status, Query, HTTPException, Request
from app.schemas.Order import Order
from app.services import CommissionerService as commissionerService
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from typing import Optional

commissionerRouter = APIRouter(prefix="/commissioner")


@commissionerRouter.get("/{commissioner_id}/offers")
def find_offers(
    commissioner_id: str,
    min_price: Optional[float] = Query(title="min_price", default=None),
    max_price: Optional[float] = Query(title="max_price", default=None),
    from_date: Optional[str] = Query(title="from_date", default=None),
    to_date: Optional[str] = Query(title="to_date", default=None),
    offer_status: Optional[str] = Query(title="offer_status", default=None),
    search_argument: Optional[str] = Query(title="search_argument", default=None)
):
    try:
        response = commissionerService.get_commissioner_offers(
            commissioner_id=commissioner_id,
            min_price=min_price,
            max_price=max_price,
            from_date=from_date,
            to_date=to_date,
            offer_status=offer_status,
            search_argument=search_argument
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=get_unsuccessful_response(str(e)))


@commissionerRouter.get("/{commissioner_id}/orders")
def find_orders(commissioner_id: str):
    try:
        response = commissionerService.get_commissioner_orders(commissioner_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except HTTPException as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=get_unsuccessful_response(str(e)))


@commissionerRouter.post("/accept-offer")
def accept_offer(request: Request, payload=Body(...)):
    try:

        user = request.state._state.get('user')
        groupSelected = request.state._state.get('groupSelected')
        user_token = None
        authorization = request.headers.get("Authorization")
        if authorization and authorization.startswith("Bearer "):
            user_token = authorization.replace("Bearer ", "")

        response = commissionerService.accept_commissioner_offer(
            payload["offer_id"], user_token=user_token, group_selected=groupSelected, new_price=payload["new_price"])

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))

    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content=get_unsuccessful_response(str(e)))
