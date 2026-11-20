from fastapi import APIRouter, Body, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional

from app.schemas.DeliveryFailure import (
    DELIVERY_FAILURE_MAX_NOTE_LEN,
    DELIVERY_FAILURE_MAX_PHOTOS,
    DeliveryFailureReason,
)

from app.services import DeliveryService
from app.services import RouteService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

deliveryRouter = APIRouter(tags=["Delivery"])


# ---------------------------------------------------------------------------
# GET /delivery-persons  — list registered delivery persons in a group
# ---------------------------------------------------------------------------

@deliveryRouter.get("/delivery-persons", description="List active delivery persons for a group")
@deliveryRouter.get("/delivery-persons/", include_in_schema=False)
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
    completion_range: Optional[str] = Query(
        None,
        alias="completion_range",
        description="For status=RECIEVED only: today, yesterday, last_3_days, last_7_days, last_30_days",
    ),
):
    try:
        requesting_uid = request.state.user.get("uid")
        result = DeliveryService.get_my_orders(requesting_uid, status_filter, completion_range)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


# ---------------------------------------------------------------------------
# GET /delivery/guest-orders  — orders assigned to a guest token (public)
# ---------------------------------------------------------------------------

@deliveryRouter.get("/delivery/guest-orders", description="Orders assigned to a guest delivery token")
def get_guest_orders(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
):
    try:
        token = request.headers.get("X-Guest-Token")
        if not token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content=get_unsuccessful_response(Exception("Missing X-Guest-Token header")),
            )
        result = DeliveryService.get_guest_orders(token, status_filter)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


@deliveryRouter.get(
    "/delivery/guest-orders/{order_id}",
    description="Single order assigned to a guest delivery token",
)
def get_guest_order_by_id(
    request: Request,
    order_id: str,
):
    try:
        token = request.headers.get("X-Guest-Token")
        if not token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content=get_unsuccessful_response(Exception("Missing X-Guest-Token header")),
            )
        result = DeliveryService.get_guest_order_by_id(token, order_id)
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
# GET /delivery/invite/{token}/eligibility  — authenticated role check
# ---------------------------------------------------------------------------

@deliveryRouter.get("/delivery/invite/{token}/eligibility", description="Check if logged-in user can accept invite orders")
def get_invite_eligibility(token: str, request: Request):
    try:
        requesting_uid = request.state.user.get("uid")
        result = DeliveryService.get_invite_eligibility(token, requesting_uid)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
        return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


# ---------------------------------------------------------------------------
# POST /delivery/invite/{token}/link  — link eligible orders to authenticated user
# ---------------------------------------------------------------------------

@deliveryRouter.post("/delivery/invite/{token}/link", description="Link eligible invite orders to the authenticated delivery person")
def link_invite(token: str, request: Request):
    try:
        requesting_uid = request.state.user.get("uid")
        result = DeliveryService.link_authenticated_delivery_person(token, requesting_uid)
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


# ---------------------------------------------------------------------------
# Guest notification feed — X-Guest-Token only (never body or query)
# ---------------------------------------------------------------------------

def _error_response(e: Exception) -> JSONResponse:
    # Errors with a machine code the client branches on (guest_token_inactive, route_estimates_unavailable).
    if isinstance(e, (DeliveryService.GuestTokenInactive, RouteService.RouteEstimatesUnavailable)):
        return JSONResponse(status_code=e.status_code, content={"code": e.code, "error": str(e.detail)})
    status_code = e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(status_code=status_code, content=get_unsuccessful_response(e))


def _missing_guest_token() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=get_unsuccessful_response(Exception("Missing X-Guest-Token header")),
    )


@deliveryRouter.get("/delivery/guest-notifications", description="Delivery alerts for a guest token")
def get_guest_notifications(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1),
):
    token = request.headers.get("X-Guest-Token")
    if not token:
        return _missing_guest_token()
    try:
        result = DeliveryService.get_guest_notifications(token, skip, limit)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        return _error_response(e)


class GuestNotificationsReadBody(BaseModel):
    ids: Optional[List[str]] = None


@deliveryRouter.post("/delivery/guest-notifications/read", description="Mark a guest's alerts read (no ids = all)")
def mark_guest_notifications_read(request: Request, data: GuestNotificationsReadBody = Body(default_factory=GuestNotificationsReadBody)):
    token = request.headers.get("X-Guest-Token")
    if not token:
        return _missing_guest_token()
    try:
        result = DeliveryService.mark_guest_notifications_read(token, data.ids)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        return _error_response(e)


# ---------------------------------------------------------------------------
# POST /delivery/report-failed  — account (bearer) or guest (X-Guest-Token)
# ---------------------------------------------------------------------------

class ReportFailedBody(BaseModel):
    order_id: str = Field(..., min_length=1)
    reason: DeliveryFailureReason
    note: Optional[str] = Field(None, max_length=DELIVERY_FAILURE_MAX_NOTE_LEN)
    photo_urls: List[str] = Field(default_factory=list, max_length=DELIVERY_FAILURE_MAX_PHOTOS)
    client_attempt_id: Optional[str] = Field(None, max_length=100)


def _caller(request: Request) -> tuple[Optional[str], Optional[str]]:
    """(user_uid, guest_token): the guest token comes only from the header."""
    guest_token = request.headers.get("X-Guest-Token")
    if guest_token:
        return None, guest_token
    user = getattr(request.state, "user", None) or {}
    return user.get("uid"), None


@deliveryRouter.post("/delivery/report-failed", description="Rider reports a failed delivery attempt")
def report_failed(request: Request, data: ReportFailedBody):
    user_uid, guest_token = _caller(request)
    if not user_uid and not guest_token:
        return _missing_guest_token()
    try:
        result = DeliveryService.report_failed(
            order_id=data.order_id,
            reason=data.reason,
            note=data.note,
            photo_urls=data.photo_urls,
            client_attempt_id=data.client_attempt_id,
            user_uid=user_uid,
            guest_token=guest_token,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        return _error_response(e)


# ---------------------------------------------------------------------------
# POST /delivery/route-legs  — km and minutes per stop (Google Directions, cached)
# ---------------------------------------------------------------------------

class LatLng(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class RouteLegsBody(BaseModel):
    origin: LatLng
    stops: List[LatLng] = Field(default_factory=list, max_length=RouteService.MAX_STOPS)


@deliveryRouter.post("/delivery/route-legs", description="Distance and time per stop, in the order sent")
def route_legs(request: Request, data: RouteLegsBody):
    user_uid, guest_token = _caller(request)
    if not user_uid and not guest_token:
        return _missing_guest_token()
    try:
        if guest_token:
            DeliveryService.require_active_guest(guest_token)
        else:
            DeliveryService._assert_has_delivery_role(user_uid)  # deliveries.perform
        legs = RouteService.get_route_legs(data.origin.model_dump(), [s.model_dump() for s in data.stops])
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response({"legs": legs}))
    except Exception as e:
        return _error_response(e)
