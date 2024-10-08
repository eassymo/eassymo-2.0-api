from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query
from app.schemas.Order import Order
from app.services import OrderService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response


orderRouter = APIRouter(prefix="/order")


@orderRouter.get("", description="returns the list of orders")
def find(group_id: str = Query(None, title="group_id"), current_role: str = Query(None, title="current_role")):
    try:
        response = OrderService.find(group_id, current_role)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
