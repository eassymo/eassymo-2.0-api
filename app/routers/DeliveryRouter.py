from fastapi import APIRouter, Body, Query, Request, status
from fastapi.responses import JSONResponse
from typing import Optional

from app.services import DeliveryService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

deliveryRouter = APIRouter(tags=["Delivery"])


# ---------------------------------------------------------------------------
# GET /delivery-persons  — list registered delivery persons in a group
# ---------------------------------------------------------------------------

@deliveryRouter.get("/delivery-persons", description="List active delivery persons for a group")
def get_delivery_persons(
    request: Request,
    group_id: str = Query(..., title="group_id"),
):
    try:
        requesting_uid = request.state.user.get("uid")
        result = DeliveryService.get_delivery_persons(group_id, requesting_uid)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


# ---------------------------------------------------------------------------
# GET /delivery/my-orders  — orders assigned to the authenticated delivery person
# ---------------------------------------------------------------------------

@deliveryRouter.get("/delivery/my-orders", description="Orders assigned to the authenticated delivery person")
def get_my_orders(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
):
    try:
        requesting_uid = request.state.user.get("uid")
        result = DeliveryService.get_my_orders(requesting_uid, status_filter)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


# ---------------------------------------------------------------------------
# GET /delivery/guest-orders  — orders assigned to a guest token (public)
# ---------------------------------------------------------------------------

@deliveryRouter.get("/delivery/guest-orders", description="Orders assigned to a guest delivery token")
def get_guest_orders(
    token: str = Query(..., title="token"),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    try:
        result = DeliveryService.get_guest_orders(token, status_filter)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


# ---------------------------------------------------------------------------
# GET /delivery-invite/{token}  — public invite preview page data
# ---------------------------------------------------------------------------

@deliveryRouter.get("/delivery-invite/{token}", description="Public invite preview for a guest delivery token")
def get_invite_preview(token: str):
    try:
        result = DeliveryService.get_invite_preview(token)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


# ---------------------------------------------------------------------------
# POST /delivery-invite/{token}/accept  — guest accepts the delivery invite
# ---------------------------------------------------------------------------

@deliveryRouter.post("/delivery-invite/{token}/accept", description="Guest accepts the delivery invite")
def accept_invite(token: str):
    try:
        result = DeliveryService.accept_invite(token)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


# ---------------------------------------------------------------------------
# POST /delivery/confirm-pickup  — guest confirms physical collection
# ---------------------------------------------------------------------------

@deliveryRouter.post("/delivery/confirm-pickup", description="Guest confirms they have physically collected the order")
def confirm_pickup(request: Request, data: dict = Body(...)):
    try:
        guest_token = request.headers.get("X-Guest-Token")
        if not guest_token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content=get_unsuccessful_response("Missing X-Guest-Token header"),
            )

        order_id = data.get("order_id")
        if not order_id:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response("order_id is required"),
            )

        result = DeliveryService.confirm_pickup(
            guest_token=guest_token,
            order_id=order_id,
            delivery_notes_seller=data.get("delivery_notes_seller"),
            delivery_pictures_seller=data.get("delivery_pictures_seller"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))
