from fastapi import HTTPException
from bson import ObjectId
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4
from typing import Optional, List

from app.repositories import (
    OrderRepository as orderRepository,
    UserRepository as userRepository,
    UserRolesRepository as userRolesRepository,
    GuestDeliveryProfileRepository as guestProfileRepository,
)
from app.schemas.Order import Order, DeliveryAssignment, DeliveryAssignmentType, OrderStatus
from app.schemas.GuestDeliveryProfile import GuestDeliveryProfile, GuestDeliveryProfileStatus
from app.schemas.Groups import GroupSchema

# Role value for delivery persons (DEALER_SHOP in the UserRoles enum)
DELIVERY_PERSON_ROLE_VALUE = "215"


# ---------------------------------------------------------------------------
# GET /delivery-persons
# ---------------------------------------------------------------------------

def get_delivery_persons(group_id: str, requesting_user_uid: str) -> List[dict]:
    """
    Returns all active users with the DELIVERY_PERSON role that belong to group_id.
    The requesting user must also belong to that group.
    """
    _assert_user_in_group(requesting_user_uid, group_id)

    role_records = userRolesRepository.find({
        "role": DELIVERY_PERSON_ROLE_VALUE,
        "group": group_id,
        "active": True,
    })

    uids = [r.user_uid for r in role_records]

    if not uids:
        return []

    users = list(userRepository.find({"uid": {"$in": uids}}, limit=200))

    result = []
    for u in users:
        result.append({
            "_id": str(u.get("_id", "")),
            "name": u.get("name"),
            "phone": u.get("phone"),
            "email": u.get("email"),
            "uid": u.get("uid"),
        })

    return result


# ---------------------------------------------------------------------------
# POST /order/assign-delivery  (core logic — called from OrderService)
# ---------------------------------------------------------------------------

def build_delivery_assignment(
    assignment_type: str,
    user_id: Optional[str],
    guest_name: Optional[str],
    guest_phone: Optional[str],
    group_id: str,
    guest_token: Optional[str] = None,
) -> DeliveryAssignment:
    """
    Validates assignment inputs and returns a ready-to-persist DeliveryAssignment.
    Upserts GuestDeliveryProfile when assignment_type == 'guest'.
    Raises HTTPException on any validation failure.
    """
    now = datetime.now(ZoneInfo('UTC'))

    if assignment_type == DeliveryAssignmentType.GROUP_MEMBER:
        if not user_id:
            raise HTTPException(status_code=422, detail="user_id is required for group_member assignment")

        role_match = userRolesRepository.find({
            "user_uid": user_id,
            "role": DELIVERY_PERSON_ROLE_VALUE,
            "group": group_id,
            "active": True,
        })

        if not role_match:
            raise HTTPException(
                status_code=404,
                detail="Delivery user not found or does not have the DELIVERY_PERSON role in this group"
            )

        return DeliveryAssignment(
            type=DeliveryAssignmentType.GROUP_MEMBER,
            user_id=user_id,
            assigned_at=now,
        )

    elif assignment_type == DeliveryAssignmentType.GUEST:
        if not guest_name:
            raise HTTPException(status_code=422, detail="guest_name are required for guest assignment")

        if guest_token:
            # Caller supplied an existing token — use it directly
            token = guest_token
        else:
            token = _upsert_guest_profile(guest_phone, guest_name)

        return DeliveryAssignment(
            type=DeliveryAssignmentType.GUEST,
            guest_token=token,
            guest_name=guest_name,
            guest_phone=guest_phone,
            assigned_at=now,
        )

    else:
        raise HTTPException(status_code=422, detail=f"Invalid assignment_type: {assignment_type}")


def get_guest_token_for_invite(guest_phone: str) -> str:
    """Returns the token that was assigned to guest_phone (must already exist)."""
    profile = guestProfileRepository.find_by_phone(guest_phone)
    if not profile:
        raise HTTPException(status_code=404, detail="Guest profile not found")
    return profile["token"]


# ---------------------------------------------------------------------------
# GET /delivery/my-orders
# ---------------------------------------------------------------------------

def get_my_orders(user_uid: str, status_filter: Optional[str]) -> List[dict]:
    """
    Returns orders where delivery_assignment.user_id == user_uid.
    The user must have the DELIVERY_PERSON role.
    """
    _assert_has_delivery_role(user_uid)

    filters: dict = {"delivery_assignment.user_id": user_uid}
    if status_filter:
        filters["status"] = status_filter

    return _fetch_orders_for_delivery(filters)


# ---------------------------------------------------------------------------
# GET /delivery/guest-orders
# ---------------------------------------------------------------------------

def get_guest_orders(token: str, status_filter: Optional[str]) -> List[dict]:
    """
    Returns orders assigned to a guest token.
    Token must belong to an active GuestDeliveryProfile.
    """
    _assert_guest_token_active(token)

    filters: dict = {
        "delivery_assignment.guest_token": token,
        "status": {"$ne": OrderStatus.CANCELED.value},
    }
    if status_filter:
        filters["status"] = status_filter

    return _fetch_orders_for_delivery(filters)


# ---------------------------------------------------------------------------
# GET /delivery-invite/:token
# ---------------------------------------------------------------------------

def get_invite_preview(token: str) -> dict:
    profile_doc = guestProfileRepository.find_by_token(token)
    if not profile_doc or profile_doc.get("status") != GuestDeliveryProfileStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Invite token not found or inactive")

    orders = _fetch_orders_for_delivery({"delivery_assignment.guest_token": token})

    latest_order = orders[0] if orders else None

    return {
        "guest_name": profile_doc["name"],
        "guest_phone": profile_doc["phone"],
        "orders_count": len(orders),
        "latest_order": latest_order,
    }


# ---------------------------------------------------------------------------
# POST /delivery-invite/:token/accept
# ---------------------------------------------------------------------------

def accept_invite(token: str) -> dict:
    profile_doc = guestProfileRepository.find_by_token(token)
    if not profile_doc or profile_doc.get("status") != GuestDeliveryProfileStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Invite token not found or inactive")

    now = datetime.now(ZoneInfo('UTC'))
    guestProfileRepository.update(
        {"token": token},
        {"accepted_at": now, "updated_at": now},
    )

    orders = _fetch_orders_for_delivery({"delivery_assignment.guest_token": token})

    return {
        "token": token,
        "orders": orders,
    }


# ---------------------------------------------------------------------------
# Guest token validation helper (used by change-status endpoint)
# ---------------------------------------------------------------------------

def validate_guest_token(token: str) -> dict:
    """
    Returns the GuestDeliveryProfile document if the token is active.
    Raises 404 if not found / inactive.
    """
    profile_doc = guestProfileRepository.find_by_token(token)
    if not profile_doc or profile_doc.get("status") != GuestDeliveryProfileStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Guest token not found or inactive")
    return profile_doc


# ---------------------------------------------------------------------------
# POST /delivery/confirm-pickup
# ---------------------------------------------------------------------------

def confirm_pickup(
    guest_token: str,
    order_id: str,
    delivery_notes_seller: Optional[str] = None,
    delivery_pictures_seller: Optional[List[str]] = None,
) -> dict:
    """
    Called by a guest delivery person to confirm physical collection of an order.
    Advances order status from WAITING_FOR_COLLECTION → DISPATCHED.
    """
    from bson import ObjectId

    profile_doc = guestProfileRepository.find_by_token(guest_token)
    if not profile_doc or profile_doc.get("status") != GuestDeliveryProfileStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="Missing or unrecognised X-Guest-Token")

    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found")

    order_doc = orderRepository.find_one({"_id": oid})
    if not order_doc:
        raise HTTPException(status_code=404, detail="Order not found")

    assigned_token = (order_doc.get("delivery_assignment") or {}).get("guest_token")
    if assigned_token != guest_token:
        raise HTTPException(status_code=403, detail="Token does not match order delivery assignment")

    order = Order(**order_doc)

    if order.status != OrderStatus.WAITING_FOR_COLLECTION:
        raise HTTPException(
            status_code=409,
            detail=f"Order is not in WAITING_FOR_COLLECTION status (current: {order.status.value})"
        )

    now = datetime.now(ZoneInfo('UTC'))
    order.change_status(OrderStatus.DISPATCHED.name)

    if delivery_notes_seller is not None:
        order.delivery_notes_seller = delivery_notes_seller
    if delivery_pictures_seller:
        order.delivery_pictures_seller = delivery_pictures_seller

    order_data = order.toJson()
    order_data.pop("_id", None)

    updated_doc = orderRepository.edit(oid, order_data)
    return Order(**updated_doc).toJson()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _upsert_guest_profile(phone: str, name: str) -> str:
    existing = guestProfileRepository.find_by_phone(phone)
    if existing and existing.get("status") == GuestDeliveryProfileStatus.ACTIVE:
        return existing["token"]

    now = datetime.now(ZoneInfo('UTC'))
    token = str(uuid4())
    profile = GuestDeliveryProfile(
        phone=phone,
        name=name,
        token=token,
        created_at=now,
        updated_at=now,
        status=GuestDeliveryProfileStatus.ACTIVE,
    )
    payload = profile.model_dump(by_alias=True)
    payload.pop("_id", None)
    guestProfileRepository.insert(payload)
    return token


def _assert_user_in_group(user_uid: str, group_id: str):
    user = userRepository.find_one({"uid": user_uid})
    if not user:
        raise HTTPException(status_code=404, detail="Requesting user not found")
    groups = user.get("groups", [])
    if group_id not in groups:
        raise HTTPException(status_code=403, detail="Requesting user does not belong to this group")


def _assert_has_delivery_role(user_uid: str):
    role_records = userRolesRepository.find({
        "user_uid": user_uid,
        "role": DELIVERY_PERSON_ROLE_VALUE,
        "active": True,
    })
    if not role_records:
        raise HTTPException(status_code=403, detail="User does not have the DELIVERY_PERSON role")


def _assert_guest_token_active(token: str):
    profile_doc = guestProfileRepository.find_by_token(token)
    if not profile_doc or profile_doc.get("status") != GuestDeliveryProfileStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Guest token not found or inactive")


def _fetch_orders_for_delivery(filters: dict) -> List[dict]:
    orders_raw = list(orderRepository.find(filters))
    result = []
    for order_data in orders_raw:
        order_json = Order(**order_data).toJson()
        if "offer_group" in order_data and order_data["offer_group"]:
            order_json["offer_group"] = GroupSchema(**order_data["offer_group"]).toJson()
        if "request_group" in order_data and order_data["request_group"]:
            order_json["request_group"] = GroupSchema(**order_data["request_group"]).toJson()
        # Strip sensitive pricing fields from the offer
        if "offer" in order_json and order_json["offer"]:
            for field in ("price", "margin", "unit_price", "total_price"):
                order_json["offer"].pop(field, None)
        result.append(order_json)
    return result
