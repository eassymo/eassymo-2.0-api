from fastapi import APIRouter, Body, status, Query, HTTPException, Request
from app.schemas.Order import Order
from app.services import CommissionerService as commissionerService
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response


commissionerRouter = APIRouter(prefix="/commissioner")

@commissionerRouter.get("/{commissioner_id}/offers")
def find_offers(commissioner_id: str):
    try:
        response = commissionerService.get_commissioner_offers(commissioner_id)
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
