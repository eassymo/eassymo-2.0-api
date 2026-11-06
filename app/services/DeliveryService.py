from fastapi import HTTPException
from bson import ObjectId
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4
from typing import Optional, List, Tuple

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

# Calendar bounds for "completed" filters match es-MX expectations (same as typical driver timezone).
DELIVERY_COMPLETION_STATS_TZ = ZoneInfo("America/Mexico_City")

_COMPLETION_RANGE_VALUES = frozenset({
    "today",
    "yesterday",
    "last_3_days",
    "last_7_days",
    "last_30_days",
})


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
            token = _ensure_guest_profile(guest_token, guest_name, guest_phone)
        elif guest_phone:
            token = _upsert_guest_profile(guest_phone, guest_name)
        else:
            token = _ensure_guest_profile(str(uuid4()), guest_name, None)

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


def _resolve_completion_range_bounds(completion_range: str) -> tuple[datetime, datetime]:
    """
    Inclusive local calendar windows in DELIVERY_COMPLETION_STATS_TZ,
    returned as timezone-aware UTC datetimes for Mongo updated_at queries.
    """
    tz = DELIVERY_COMPLETION_STATS_TZ
    now_local = datetime.now(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_today = today_start + timedelta(days=1) - timedelta(microseconds=1)

    if completion_range == "today":
        start_local = today_start
        end_local = end_of_today
    elif completion_range == "yesterday":
        start_local = today_start - timedelta(days=1)
        end_local = today_start - timedelta(microseconds=1)
    elif completion_range == "last_3_days":
        start_local = today_start - timedelta(days=2)
        end_local = end_of_today
    elif completion_range == "last_7_days":
        start_local = today_start - timedelta(days=6)
        end_local = end_of_today
    elif completion_range == "last_30_days":
        start_local = today_start - timedelta(days=29)
        end_local = end_of_today
    else:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid completion_range. Allowed: {sorted(_COMPLETION_RANGE_VALUES)}",
        )

    utc = ZoneInfo("UTC")
    return start_local.astimezone(utc), end_local.astimezone(utc)


def get_my_orders(
    user_uid: str,
    status_filter: Optional[str],
    completion_range: Optional[str] = None,
) -> List[dict]:
    """
    Returns orders where delivery_assignment.user_id == user_uid.
    The user must have the DELIVERY_PERSON role.
    When status_filter is RECIEVED and completion_range is set, filters by updated_at
    (set when the order was marked received — MVP; see plan re: received_at).
    """
    _assert_has_delivery_role(user_uid)

    filters: dict = {"delivery_assignment.user_id": user_uid}
    if status_filter:
        filters["status"] = status_filter

    if completion_range:
        if status_filter != OrderStatus.RECIEVED.value:
            completion_range = None
        elif completion_range not in _COMPLETION_RANGE_VALUES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid completion_range. Allowed: {sorted(_COMPLETION_RANGE_VALUES)}",
            )

    completion_bounds: Optional[Tuple[datetime, datetime]] = None
    if completion_range and status_filter == OrderStatus.RECIEVED.value:
        completion_bounds = _resolve_completion_range_bounds(completion_range)

    return _fetch_orders_for_delivery(filters, updated_at_completion_bounds=completion_bounds)


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


def get_guest_order_by_id(token: str, order_id: str) -> dict:
    """
    Returns a single order assigned to a guest token.
    Accepts Mongo _id or human-readable order_id.
    """
    _assert_guest_token_active(token)

    id_filters: List[dict] = [{"order_id": order_id}]
    try:
        id_filters.append({"_id": ObjectId(order_id)})
    except Exception:
        pass

    filters: dict = {
        "delivery_assignment.guest_token": token,
        "status": {"$ne": OrderStatus.CANCELED.value},
        "$or": id_filters,
    }

    orders = _fetch_orders_for_delivery(filters)
    if not orders:
        raise HTTPException(status_code=404, detail="Order not found for this guest token")
    return orders[0]


# ---------------------------------------------------------------------------
# GET /delivery-invite/:token
# ---------------------------------------------------------------------------

def _resolve_active_guest_profile(token: str) -> dict:
    """
    Returns an active GuestDeliveryProfile for token.
    Backfills the profile from order delivery_assignment when missing (legacy assignments).
    """
    profile_doc = guestProfileRepository.find_by_token(token)
    if profile_doc and profile_doc.get("status") == GuestDeliveryProfileStatus.ACTIVE:
        return profile_doc

    orders = _fetch_orders_for_delivery({"delivery_assignment.guest_token": token})
    if not orders:
        raise HTTPException(status_code=404, detail="Invite token not found or inactive")

    assignment = orders[0].get("delivery_assignment") or {}
    guest_name = assignment.get("guest_name") or "Invitado"
    guest_phone = assignment.get("guest_phone")
    _ensure_guest_profile(token, guest_name, guest_phone)

    profile_doc = guestProfileRepository.find_by_token(token)
    if not profile_doc or profile_doc.get("status") != GuestDeliveryProfileStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Invite token not found or inactive")
    return profile_doc


def get_invite_preview(token: str) -> dict:
    profile_doc = _resolve_active_guest_profile(token)

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
    _resolve_active_guest_profile(token)

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
# GET /delivery/invite/{token}/eligibility  — authenticated role check
# ---------------------------------------------------------------------------

def _user_has_delivery_role_in_group(user_uid: str, group_id: str) -> bool:
    if not group_id:
        return False
    role_records = userRolesRepository.find({
        "user_uid": user_uid,
        "role": DELIVERY_PERSON_ROLE_VALUE,
        "group": str(group_id),
        "active": True,
    })
    return bool(role_records)


def get_invite_eligibility(token: str, user_uid: str) -> dict:
    """
    Per-order check: does user_uid hold the active DELIVERY_PERSON role
    in the offer.group_id (seller group) of each order tied to this guest token?
    Only orders still in WAITING_FOR_COLLECTION are considered linkable.
    """
    _resolve_active_guest_profile(token)

    orders = _fetch_orders_for_delivery({
        "delivery_assignment.guest_token": token,
        "status": OrderStatus.WAITING_FOR_COLLECTION.value,
    })

    eligible_orders = [
        o for o in orders
        if _user_has_delivery_role_in_group(
            user_uid,
            (o.get("offer_group") or {}).get("_id"),
        )
    ]

    return {
        "eligible_orders": eligible_orders,
        "has_any_eligible_order": bool(eligible_orders),
    }


# ---------------------------------------------------------------------------
# POST /delivery/invite/{token}/link  — reassign eligible orders to user
# ---------------------------------------------------------------------------

def link_authenticated_delivery_person(token: str, user_uid: str) -> dict:
    """Reassigns each eligible order's delivery_assignment from guest_token to this user."""
    eligibility = get_invite_eligibility(token, user_uid)
    if not eligibility["has_any_eligible_order"]:
        raise HTTPException(
            status_code=403,
            detail="User does not have the repartidor role for any order in this invite",
        )

    linked = []
    now = datetime.now(ZoneInfo('UTC'))
    for order_json in eligibility["eligible_orders"]:
        oid = ObjectId(order_json["_id"])
        order_doc = orderRepository.find_one({"_id": oid})
        if not order_doc:
            continue

        order = Order(**order_doc)
        order.delivery_assignment = DeliveryAssignment(
            type=DeliveryAssignmentType.GROUP_MEMBER,
            user_id=user_uid,
            assigned_at=now,
        )
        order_data = order.toJson()
        order_data.pop("_id", None)
        updated_doc = orderRepository.edit(oid, order_data)
        linked.append(Order(**updated_doc).toJson())

    return {"linked_orders": linked}


# ---------------------------------------------------------------------------
# Guest token validation helper (used by change-status endpoint)
# ---------------------------------------------------------------------------

def validate_guest_token(token: str) -> dict:
    """
    Returns the GuestDeliveryProfile document if the token is active.
    Raises 404 if not found / inactive.
    """
    return _resolve_active_guest_profile(token)


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

    _resolve_active_guest_profile(guest_token)

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


def _ensure_guest_profile(token: str, name: str, phone: Optional[str] = None) -> str:
    """
    Ensures an active GuestDeliveryProfile exists for a client-supplied invite token.
    The assign-delivery UI pre-generates the token so the invite URL is available before submit.
    """
    now = datetime.now(ZoneInfo('UTC'))
    profile_phone = phone or f"guest:{token}"

    existing_by_token = guestProfileRepository.find_by_token(token)
    if existing_by_token:
        updates = {"name": name, "updated_at": now, "status": GuestDeliveryProfileStatus.ACTIVE}
        if phone:
            updates["phone"] = phone
        guestProfileRepository.update({"token": token}, updates)
        return token

    if phone:
        existing_by_phone = guestProfileRepository.find_by_phone(phone)
        if existing_by_phone:
            guestProfileRepository.update(
                {"phone": phone},
                {
                    "token": token,
                    "name": name,
                    "updated_at": now,
                    "status": GuestDeliveryProfileStatus.ACTIVE,
                },
            )
            return token

    profile = GuestDeliveryProfile(
        phone=profile_phone,
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
    _resolve_active_guest_profile(token)


def _fetch_orders_for_delivery(
    filters: dict,
    updated_at_completion_bounds: Optional[Tuple[datetime, datetime]] = None,
) -> List[dict]:
    orders_raw = list(
        orderRepository.find(filters, updated_at_completion_bounds=updated_at_completion_bounds)
    )
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
