from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, Query, Request
from app.schemas.Order import Order, OrderStatus
from app.services import OrderService
from app.services import DeliveryService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from typing import Optional

# Role value for delivery persons (DEALER_SHOP)
_DELIVERY_PERSON_ROLE = "215"

orderRouter = APIRouter(prefix="/order")


@orderRouter.get("", description="returns the list of orders", tags=["Orders"])
def find(
    id: str = Query(None, title="order_id"),
    group_id: str = Query(None, title="group_id"),
    current_role: str = Query(None, title="current_role"),
    search_argument: Optional[str] = Query(None, title="search_argument")
):
    try:
        response = OrderService.find(
            id, group_id, current_role, search_argument)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@orderRouter.post("/assign-delivery", description="Assigns a delivery person and advances order to DISPATCHED", tags=["Orders"])
def assign_delivery(request: Request, data: dict = Body(...)):
    try:
        order_id = data.get("order_id")
        assignment_type = data.get("assignment_type")
        user_id = data.get("user_id")
        guest_name = data.get("guest_name")
        guest_phone = data.get("guest_phone")
        guest_token = data.get("guest_token")

        if not order_id:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response("order_id is required"),
            )
        if not assignment_type:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response("assignment_type is required"),
            )

        requesting_uid = request.state.user.get("uid")

        response = OrderService.assign_delivery(
            order_id=order_id,
            assignment_type=assignment_type,
            requesting_user_uid=requesting_uid,
            user_id=user_id,
            guest_name=guest_name,
            guest_phone=guest_phone,
            guest_token=guest_token,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


@orderRouter.post("/change-status", description="Changes the status of the order", tags=["Orders"])
def change_order_status(request: Request, data: dict = Body(...)):
    try:
        new_status = data.get("new_status")
        order_id = data.get("order_id")

        delivery_notes_buyer = data.get("delivery_notes_buyer")
        delivery_pictures_buyer = data.get("delivery_pictures_buyer")

        delivery_notes_seller = data.get("delivery_notes_seller")
        delivery_pictures_seller = data.get("delivery_pictures_seller")

        packaged_notes_seller = data.get("packaged_notes_seller")
        packaged_pictures_seller = data.get("packaged_pictures_seller")

        if not new_status:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response("new_status is required in the request body"),
            )

        # --- Guest token path (X-Guest-Token header) ---
        guest_token = request.headers.get("X-Guest-Token")
        if guest_token:
            if new_status != OrderStatus.RECIEVED.name:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content=get_unsuccessful_response("Guest delivery persons can only mark orders as RECIEVED"),
                )
            guest_profile = DeliveryService.validate_guest_token(guest_token)
            from app.repositories import OrderRepository as orderRepository
            from bson import ObjectId
            order_doc = orderRepository.find_one({"_id": ObjectId(order_id)})
            if not order_doc:
                return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=get_unsuccessful_response("Order not found"))
            assigned_token = (order_doc.get("delivery_assignment") or {}).get("guest_token")
            if assigned_token != guest_token:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content=get_unsuccessful_response("This order is not assigned to the provided guest token"),
                )
            response = OrderService.change_order_status(
                order_id, new_status,
                delivery_notes_buyer=delivery_notes_buyer,
                delivery_notes_seller=delivery_notes_seller,
                delivery_pictures_buyer=delivery_pictures_buyer,
                delivery_pictures_seller=delivery_pictures_seller,
                packaged_notes_seller=packaged_notes_seller,
                packaged_pictures_seller=packaged_pictures_seller,
            )
            return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))

        # --- Authenticated path ---
        user = request.state.user
        user_roles = user.get("roles", [])

        if _DELIVERY_PERSON_ROLE in user_roles:
            if new_status != OrderStatus.RECIEVED.name:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content=get_unsuccessful_response("Delivery persons can only mark orders as RECIEVED"),
                )
            from app.repositories import OrderRepository as orderRepository
            from bson import ObjectId
            order_doc = orderRepository.find_one({"_id": ObjectId(order_id)})
            if not order_doc:
                return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=get_unsuccessful_response("Order not found"))
            assigned_uid = (order_doc.get("delivery_assignment") or {}).get("user_id")
            if assigned_uid != user.get("uid"):
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content=get_unsuccessful_response("This order is not assigned to you"),
                )

        response = OrderService.change_order_status(
            order_id, new_status,
            delivery_notes_buyer=delivery_notes_buyer,
            delivery_notes_seller=delivery_notes_seller,
            delivery_pictures_buyer=delivery_pictures_buyer,
            delivery_pictures_seller=delivery_pictures_seller,
            packaged_notes_seller=packaged_notes_seller,
            packaged_pictures_seller=packaged_pictures_seller,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


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
