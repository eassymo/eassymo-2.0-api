from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query
from app.schemas.Order import Order
from app.services import OrderService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response


orderRouter = APIRouter(prefix="/order")


@orderRouter.get("", description="returns the list of orders", tags=["Orders"])
def find(
    id: str = Query(None, title="order_id"),
    group_id: str = Query(None, title="group_id"),
    current_role: str = Query(None, title="current_role")
):
    try:
        response = OrderService.find(id, group_id, current_role)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@orderRouter.post("/change-status", description="Changes the status of the order", tags=["Orders"])
def change_order_status(data: dict = Body(...)):
    try:
        new_status = data.get("new_status")
        order_id = data.get("order_id")
        if not new_status:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response(
                    "new_status is required in the request body")
            )
        response = OrderService.change_order_status(order_id, new_status)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@orderRouter.get("/{id}", description="Get order by id", tags=["Orders"], response_model=Order)
def find_by_id(id: str):
    try:
        response = OrderService.find_by_id(id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@orderRouter.post("/change-delivery-time", description="Changes the delivery time of an order", tags=["Orders"])
def change_delivery_time(data: dict = Body(...)):
    try:
        response = OrderService.change_delivery_time(
            data["order_id"], data["new_delivery_time"], data["is_delayed"])
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
