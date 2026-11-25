"""Server-side notification fan-out (ADR-001 Phase 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.factories.NotificationsCreator import (
    create_callcenter_connected_group_selected_notification,
    create_callcenter_offer_approval_approved_notification,
    create_delivery_notification,
    DELIVERY_SELLER_ROLES,
    create_invite_accepted_notification,
    create_offer_approval_request_notification,
    create_offer_notification,
    create_offer_selected_notification,
    create_order_canceled_notification,
    create_order_confirmed_notification,
    create_order_delayed_notification,
    create_order_received_notification,
    create_order_ready_to_be_sent_notification,
    create_order_sent_notification,
    create_part_request_invite_notification,
    create_part_request_notification,
    create_part_request_reminder_notification,
)
from app.repositories import GroupRepository as groupRepository
from app.repositories import UserRepository as userRepository
from app.schemas.Notification import Notification, NotificationType
from app.schemas.Offer import OfferStatus
from app.schemas.Order import OrderStatus
from app.services import CallCenterService as callCenterService
from app.services import GroupService as groupService
from app.utils.notification_routes import (
    buyer_offer_review_path,
    order_management_path,
    seller_offer_creator_path,
    buyer_offer_notification_meta,
)
from app.utils.display_text import display_name, local_time_label, sentence_case, vehicle_label
from app.utils.notifications import send_notifications_batch


def persist_notification_dicts(notifications: Optional[List[Dict[str, Any]]]) -> None:
    if not notifications:
        return
    send_notifications_batch(notifications)


def persist_notification_dict(notification: Optional[Dict[str, Any]]) -> None:
    if notification:
        send_notifications_batch([notification])


def _group_name(group_id: str) -> str:
    doc = groupRepository.find_by_id(group_id)
    return (doc or {}).get("name") or ""


def _vehicle(part_request: Dict[str, Any]) -> str:
    return vehicle_label((part_request or {}).get("vehicleInformation"))


def _users_by_group_ids(group_ids: List[str]) -> List[Dict[str, Any]]:
    if not group_ids:
        return []
    return groupService.find_users_by_groups_ids_v2(group_ids)


def _callcenter_groups_for_part(
    part_request: Dict[str, Any],
    seller_ids: List[str],
    follower_ids: List[str],
    commissioner_group: Optional[str],
) -> set:
    """Selected groups this part actually went to (compatible or excluded for compatibility), plus followers.

    Without a reach plan every selected seller is one or the other on each part, so this is the whole
    selection; a capped part keeps only the sellers it was capped to."""
    if commissioner_group:
        return {str(commissioner_group)}
    on_part = {str(gid) for gid in (part_request.get("subscribedSellers") or []) if gid}
    on_part |= {
        str(item.get("group_id"))
        for item in (part_request.get("nonCompatibleSellers") or [])
        if isinstance(item, dict) and item.get("group_id")
    }
    return {str(gid) for gid in seller_ids if gid and str(gid) in on_part} | {str(gid) for gid in follower_ids if gid}


def fanout_part_request_created(
    *,
    part_requests: List[Dict[str, Any]],
    creator_group_name: str,
    subscribed_sellers: List[str],
    subscribed_followers: Optional[List[str]] = None,
    commissioner_group: Optional[str] = None,
) -> None:
    if not part_requests:
        return

    seller_group_ids = sorted(
        {
            str(group_id)
            for pr in part_requests
            for group_id in (pr.get("subscribedSellers") or [])
            if group_id
        }
    )
    if not seller_group_ids:
        return

    users_from_groups = _users_by_group_ids(seller_group_ids)
    notifications: List[Notification] = []

    for part_request in part_requests:
        part_request_id = str(part_request.get("_id") or part_request.get("id") or "")
        part_name = (part_request.get("part") or {}).get("tipoParteDescripcion") or ""
        navigate_to_url = seller_offer_creator_path(part_request_id)
        meta_data = {"requestId": part_request_id}
        # Each part reaches only its own sellers (a capped part has fewer than its siblings).
        part_sellers = {str(gid) for gid in (part_request.get("subscribedSellers") or []) if gid}

        for group_found in users_from_groups:
            group_id = str(group_found.get("_id") or "")
            if group_id not in part_sellers:
                continue
            for user_id in group_found.get("users") or []:
                notifications.append(
                    create_part_request_notification(
                        store_name=creator_group_name,
                        part_name=part_name,
                        vehicle=_vehicle(part_request),
                        owner=str(user_id),
                        owner_group=group_id,
                        navigate_to_url=navigate_to_url,
                        meta_data=meta_data,
                    )
                )

    follower_ids = list(subscribed_followers or [])
    seller_ids = list(subscribed_sellers or [])
    callcenter_group_ids = (
        [str(commissioner_group)]
        if commissioner_group
        else sorted({str(gid) for gid in [*seller_ids, *follower_ids] if gid})
    )

    callcenter_users = callCenterService.get_users_of_callcenters_from_group_ids(callcenter_group_ids)
    group_names = {str(gid): _group_name(str(gid)) for gid in callcenter_group_ids}

    for part_request in part_requests:
        part_groups = _callcenter_groups_for_part(part_request, seller_ids, follower_ids, commissioner_group)
        for cc_user in callcenter_users:
            cc_group_id = str(cc_user.get("group_id") or "")
            if cc_group_id not in part_groups:
                continue
            invited_group_name = group_names.get(cc_group_id, "")
            if not invited_group_name:
                continue
            notifications.append(
                create_callcenter_connected_group_selected_notification(
                    invited_group_name=invited_group_name,
                    vehicle=_vehicle(part_request),
                    owner=str(cc_user.get("user_id") or ""),
                    owner_group=str(cc_user.get("callcenter_id") or ""),
                    navigate_to_url="/callcenter-selection",
                    meta_data={"partRequest": part_request},
                )
            )

    if notifications:
        send_notifications_batch(notifications)


def fanout_part_request_to_new_sellers(
    *,
    part_request: Dict[str, Any],
    creator_group_name: str,
    new_seller_group_ids: List[str],
) -> None:
    if not part_request or not new_seller_group_ids:
        return

    part_request_id = str(part_request.get("_id") or part_request.get("id") or "")
    part_name = (part_request.get("part") or {}).get("tipoParteDescripcion") or ""
    navigate_to_url = seller_offer_creator_path(part_request_id)
    meta_data = {"requestId": part_request_id}

    notifications: List[Notification] = []
    for group_found in _users_by_group_ids(new_seller_group_ids):
        group_id = str(group_found.get("_id") or "")
        for user_id in group_found.get("users") or []:
            notifications.append(
                create_part_request_notification(
                    store_name=creator_group_name,
                    part_name=part_name,
                    vehicle=_vehicle(part_request),
                    owner=str(user_id),
                    owner_group=group_id,
                    navigate_to_url=navigate_to_url,
                    meta_data=meta_data,
                )
            )

    if notifications:
        send_notifications_batch(notifications)


def _offer_review_meta(part_request: Dict[str, Any], offer_id: str) -> Dict[str, Any]:
    request_id = str(part_request.get("_id") or part_request.get("id") or "")
    parent = part_request.get("parent_request_uid")
    return buyer_offer_notification_meta(
        request_id=request_id,
        parent_request_uid=str(parent) if parent else None,
        offer_id=offer_id,
    )


def _offer_review_url(part_request: Dict[str, Any]) -> str:
    request_id = str(part_request.get("_id") or part_request.get("id") or "")
    parent = part_request.get("parent_request_uid")
    return buyer_offer_review_path(request_id, str(parent) if parent else None)


def fanout_offer_after_insert(
    *,
    offer_payload: Dict[str, Any],
    part_request: Dict[str, Any],
    offer_id: str,
) -> None:
    if part_request.get("commissioner_group"):
        return

    status = offer_payload.get("status")
    if isinstance(status, OfferStatus):
        status_value = status.value
    else:
        status_value = str(status or "")

    part_name = (part_request.get("part") or {}).get("tipoParteDescripcion") or ""
    meta_data = _offer_review_meta(part_request, offer_id)
    navigate_to_url = _offer_review_url(part_request)
    notifications: List[Notification] = []

    if status_value == OfferStatus.pending_approval.value:
        cc_info = offer_payload.get("call_center_that_posted_offer") or {}
        cc_name = cc_info.get("name") if isinstance(cc_info, dict) else _group_name(str(cc_info or ""))
        target_group = str(offer_payload.get("group_id") or "")
        for group_found in _users_by_group_ids([target_group] if target_group else []):
            group_id = str(group_found.get("_id") or target_group)
            for user_id in group_found.get("users") or []:
                notifications.append(
                    create_offer_approval_request_notification(
                        call_center_name=cc_name or "Call Center",
                        part_name=part_name,
                        price=offer_payload.get("price"),
                        vehicle=_vehicle(part_request),
                        offer_id=offer_id,
                        owner=str(user_id),
                        owner_group=group_id,
                        navigate_to_url=navigate_to_url,
                        meta_data=meta_data,
                    )
                )
    elif status_value == OfferStatus.created.value:
        group_info = offer_payload.get("group_info") or {}
        store_name = group_info.get("name") if isinstance(group_info, dict) else _group_name(str(offer_payload.get("group_id") or ""))
        creator_group = str(part_request.get("creatorGroup") or "")
        for group_found in _users_by_group_ids([creator_group] if creator_group else []):
            group_id = str(group_found.get("_id") or creator_group)
            for user_id in group_found.get("users") or []:
                notifications.append(
                    create_offer_notification(
                        store_name=store_name or "Tienda",
                        part_name=part_name,
                        price=offer_payload.get("price"),
                        vehicle=_vehicle(part_request),
                        owner=str(user_id),
                        owner_group=group_id,
                        navigate_to_url=navigate_to_url,
                        meta_data=meta_data,
                    )
                )

    if notifications:
        send_notifications_batch(notifications)


def fanout_offer_selected(
    *,
    offer: Dict[str, Any],
    part_request: Dict[str, Any],
    order_id: str,
    buyer_store_name: str,
) -> None:
    offer_group_id = str(offer.get("group_id") or "")
    if not offer_group_id:
        return

    part_name = (part_request.get("part") or {}).get("tipoParteDescripcion") or ""
    navigate_to_url = order_management_path(order_id, current_role=2)
    meta_data = {"orderId": order_id}

    notifications: List[Notification] = []
    for group_found in _users_by_group_ids([offer_group_id]):
        group_id = str(group_found.get("_id") or offer_group_id)
        for user_id in group_found.get("users") or []:
            notifications.append(
                create_offer_selected_notification(
                    store_name=buyer_store_name or "Comprador",
                    part_name=part_name,
                    order_id=order_id,
                    price=offer.get("price"),
                    vehicle=_vehicle(part_request),
                    owner=str(user_id),
                    owner_group=group_id,
                    navigate_to_url=navigate_to_url,
                    meta_data=meta_data,
                )
            )

    if notifications:
        send_notifications_batch(notifications)


def fanout_callcenter_offer_approved(
    *,
    offer: Dict[str, Any],
    part_request: Dict[str, Any],
    approver_group_name: str,
) -> None:
    cc_info = offer.get("call_center_that_posted_offer") or {}
    cc_group_id = cc_info.get("_id") or cc_info.get("id") if isinstance(cc_info, dict) else str(cc_info or "")
    if not cc_group_id:
        return

    part_name = (part_request.get("part") or {}).get("tipoParteDescripcion") or ""
    offer_id = str(offer.get("_id") or offer.get("id") or "")
    meta_data = _offer_review_meta(part_request, offer_id)
    navigate_to_url = _offer_review_url(part_request)

    notifications: List[Notification] = []
    cc_users = callCenterService.get_users_of_callcenters_from_group_ids([str(cc_group_id)])
    for cc_user in cc_users:
        notifications.append(
            create_callcenter_offer_approval_approved_notification(
                group_name=approver_group_name or "Tienda",
                part_name=part_name,
                vehicle=_vehicle(part_request),
                owner=str(cc_user.get("user_id") or ""),
                owner_group=str(cc_user.get("callcenter_id") or ""),
                navigate_to_url=navigate_to_url,
                meta_data=meta_data,
            )
        )

    creator_group = str(part_request.get("creatorGroup") or "")
    group_info = offer.get("group_info") or {}
    store_name = group_info.get("name") if isinstance(group_info, dict) else approver_group_name
    for group_found in _users_by_group_ids([creator_group] if creator_group else []):
        group_id = str(group_found.get("_id") or creator_group)
        for user_id in group_found.get("users") or []:
            notifications.append(
                create_offer_notification(
                    store_name=store_name or approver_group_name or "Tienda",
                    part_name=part_name,
                    price=offer.get("price"),
                    vehicle=_vehicle(part_request),
                    owner=str(user_id),
                    owner_group=group_id,
                    navigate_to_url=navigate_to_url,
                    meta_data=meta_data,
                )
            )

    if notifications:
        send_notifications_batch(notifications)


def fanout_order_delayed(*, order: Dict[str, Any]) -> None:
    part_request = order.get("part_request") or {}
    owner = str(part_request.get("creatorUser") or "")
    owner_group = str(part_request.get("creatorGroup") or "")
    if not owner or not owner_group:
        return

    order_id = str(order.get("_id") or order.get("id") or "")
    part_name = (part_request.get("part") or {}).get("tipoParteDescripcion") or ""
    offer_group = order.get("offer_group") or {}
    store_name = offer_group.get("name") or _group_name(str(order.get("group") or ""))
    navigate_to_url = order_management_path(order_id, current_role=1)
    meta_data = {"orderId": order_id}

    notification = create_order_delayed_notification(
        store_name=store_name or "Tienda",
        part_name=part_name,
        order_id=order_id,
        delivery_time=order.get("to_be_delivered_time"),
        vehicle=_vehicle(part_request),
        owner=owner,
        owner_group=owner_group,
        navigate_to_url=navigate_to_url,
        meta_data=meta_data,
    )
    send_notifications_batch([notification])


def fanout_part_request_reminder(
    *,
    part_request: Dict[str, Any],
    pending_group_ids: List[str],
    store_name: str,
) -> int:
    if not part_request or not pending_group_ids:
        return 0

    part_request_id = str(part_request.get("_id") or part_request.get("id") or "")
    part_name = (part_request.get("part") or {}).get("tipoParteDescripcion") or "pieza"
    navigate_to_url = seller_offer_creator_path(part_request_id)
    meta_data = {"requestId": part_request_id}

    notifications: List[Notification] = []
    for group_found in _users_by_group_ids(pending_group_ids):
        group_id = str(group_found.get("_id") or "")
        for user_id in group_found.get("users") or []:
            notifications.append(
                create_part_request_reminder_notification(
                    store_name=store_name,
                    part_name=part_name,
                    request_id=part_request_id,
                    vehicle=_vehicle(part_request),
                    owner=str(user_id),
                    owner_group=group_id,
                    navigate_to_url=navigate_to_url,
                    meta_data=meta_data,
                )
            )

    if notifications:
        send_notifications_batch(notifications)
    return len(notifications)


def fanout_part_request_invite(
    *,
    invite_id: str,
    inviter_group_name: str,
    inviter_user: str,
    owner: str,
    owner_group: str,
    part_requests: List[Dict[str, Any]],
) -> None:
    notification = create_part_request_invite_notification(
        inviter_group_name=inviter_group_name,
        inviter_user=inviter_user,
        owner=owner,
        owner_group=owner_group,
        navigate_to_url=f"/join-request-invite/{invite_id}",
        meta_data={"partRequests": part_requests, "partRequest": part_requests[0] if part_requests else {}},
    )
    send_notifications_batch([notification])


def fanout_invite_accepted(*, owner: str, owner_group: str, store_name: str) -> None:
    notification = create_invite_accepted_notification(
        store_name=store_name,
        owner=owner,
        owner_group=owner_group,
        navigate_to_url="/dashboard-v2",
        meta_data={},
    )
    send_notifications_batch([notification])


def fanout_order_status_change(*, order: Dict[str, Any], new_status: str) -> None:
    try:
        status_enum = OrderStatus[new_status]
    except KeyError:
        return

    notification_type_map = {
        OrderStatus.CONFIRMED: NotificationType.ORDER_CONFIRMED,
        OrderStatus.READY_TO_BE_DISPATCHED: NotificationType.ORDER_READY_TO_BE_SENT,
        OrderStatus.DISPATCHED: NotificationType.ORDER_SENT,
        OrderStatus.RECIEVED: NotificationType.ORDER_RECIEVED,
    }
    notif_type = notification_type_map.get(status_enum)
    if notif_type is None:
        return

    part_request = order.get("part_request") or {}
    creator_group = str(part_request.get("creatorGroup") or "")
    if not creator_group:
        return

    order_id = str(order.get("_id") or order.get("id") or "")
    part_name = (part_request.get("part") or {}).get("tipoParteDescripcion") or ""
    offer_group = order.get("offer_group") or {}
    store_name = offer_group.get("name") or _group_name(str(order.get("offer_group_id") or ""))
    vehicle = _vehicle(part_request)
    meta_data = {"orderId": order_id}

    notifications: List[Notification] = []

    if notif_type == NotificationType.ORDER_RECIEVED:
        # The buyer confirmed it themselves; the selling store is the one who needs to know.
        seller_group = _selling_group_id(order)
        if not seller_group:
            return
        navigate_to_url = order_management_path(order_id, current_role=2)
        buyer_name = _buyer_name(order)
        for group_found in _users_by_group_ids([seller_group]):
            group_id = str(group_found.get("_id") or seller_group)
            for user_id in group_found.get("users") or []:
                notifications.append(
                    create_order_received_notification(
                        part_name=part_name,
                        order_id=order_id,
                        buyer_name=buyer_name,
                        received_at=order.get("updated_at"),
                        vehicle=vehicle,
                        owner=str(user_id),
                        owner_group=group_id,
                        navigate_to_url=navigate_to_url,
                        meta_data=meta_data,
                    )
                )
        if notifications:
            send_notifications_batch(notifications)
        return

    navigate_to_url = order_management_path(order_id, current_role=1)
    rider = ""
    if notif_type == NotificationType.ORDER_SENT and order.get("delivery_assignment"):
        rider = _rider_name(order["delivery_assignment"])
        rider = "" if rider == "otro repartidor" else rider
    for group_found in _users_by_group_ids([creator_group]):
        group_id = str(group_found.get("_id") or creator_group)
        for user_id in group_found.get("users") or []:
            owner = str(user_id)
            common = dict(
                store_name=store_name, part_name=part_name, order_id=order_id, vehicle=vehicle,
                owner=owner, owner_group=group_id, navigate_to_url=navigate_to_url, meta_data=meta_data,
            )
            if notif_type == NotificationType.ORDER_CONFIRMED:
                notifications.append(create_order_confirmed_notification(
                    delivery_time=order.get("to_be_delivered_time"), **common))
            elif notif_type == NotificationType.ORDER_READY_TO_BE_SENT:
                notifications.append(create_order_ready_to_be_sent_notification(**common))
            elif notif_type == NotificationType.ORDER_SENT:
                notifications.append(create_order_sent_notification(rider_name=rider, **common))

    if notifications:
        send_notifications_batch(notifications)


def fanout_order_canceled(*, order: Dict[str, Any], remaining_offers: int) -> None:
    """The selling store backed out: tell every user of the buyer group, with the way forward."""
    part_request = order.get("part_request") or {}
    creator_group = str(part_request.get("creatorGroup") or "")
    request_id = str(part_request.get("_id") or part_request.get("id") or "")
    if not creator_group or not request_id:
        return
    order_id = _order_id(order)
    cancellation = order.get("cancellation") or {}
    store_name = _store_name(order)
    meta_data = {"orderId": order_id, "requestId": request_id}
    notifications: List[Notification] = []
    for group_found in _users_by_group_ids([creator_group]):
        group_id = str(group_found.get("_id") or creator_group)
        for user_id in group_found.get("users") or []:
            notifications.append(create_order_canceled_notification(
                store_name=store_name,
                part_name=((part_request.get("part") or {}).get("tipoParteDescripcion") or ""),
                reason=str(cancellation.get("reason") or "other"),
                remaining_offers=remaining_offers,
                request_id=request_id,
                vehicle_id=str(part_request.get("vehicleId") or ""),
                vehicle=_vehicle(part_request),
                owner=str(user_id), owner_group=group_id, meta_data=meta_data,
            ))
    if notifications:
        send_notifications_batch(notifications)


# ── Deliveries ───────────────────────────────────────────────────────────────

DELIVERY_TZ = ZoneInfo("America/Mexico_City")

DELIVERY_FAILURE_REASON_TEXT = {
    "no_answer": "no contestan",
    "wrong_address": "la dirección no es correcta",
    "nobody_to_receive": "no había quien recibiera",
    "other": "otro motivo",
    "store_closed": "la tienda está cerrada",
    "not_ready": "todavía no está lista",
    "wrong_item": "no es la pieza correcta",
    "damaged": "la pieza llegó dañada",
}


def _user_name(uid: str) -> str:
    doc = userRepository.find_one({"uid": uid}) if uid else None
    return (doc or {}).get("name") or ""


def _order_id(order: Dict[str, Any]) -> str:
    return str(order.get("_id") or order.get("id") or "")


def _selling_group_id(order: Dict[str, Any]) -> str:
    return str(
        (order.get("offer") or {}).get("group_id")
        or (order.get("offer_group") or {}).get("_id")
        or ""
    )


def _store_name(order: Dict[str, Any]) -> str:
    return (order.get("offer_group") or {}).get("name") or _group_name(_selling_group_id(order)) or "la tienda"


def _buyer_name(order: Dict[str, Any]) -> str:
    buyer_group = str((order.get("part_request") or {}).get("creatorGroup") or "")
    return (order.get("request_group") or {}).get("name") or (_group_name(buyer_group) if buyer_group else "") or "el cliente"


def _part_name(order: Dict[str, Any]) -> str:
    return ((order.get("part_request") or {}).get("part") or {}).get("tipoParteDescripcion") or "La pieza"


def _delivery_address(order: Dict[str, Any]) -> str:
    address = ((order.get("part_request") or {}).get("delivery_address") or {}).get("address")
    return address or _buyer_name(order)


def _rider_name(assignment: Dict[str, Any]) -> str:
    if assignment.get("type") == "guest":
        return assignment.get("guest_name") or "otro repartidor"
    return _user_name(str(assignment.get("user_id") or "")) or "otro repartidor"


def _local_hhmm(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(DELIVERY_TZ).strftime("%H:%M")


def _rider_notification(
    assignment: Optional[Dict[str, Any]],
    order: Dict[str, Any],
    notification_type: NotificationType,
    title: str,
    body: str,
) -> Optional[Notification]:
    """Account rider: owned by user_id in the selling group (push included).
    Guest rider: keyed by guest_token with no owner, so no push and no account feed."""
    if not assignment:
        return None
    order_id = _order_id(order)
    group_id = _selling_group_id(order)
    if assignment.get("type") == "guest":
        token = assignment.get("guest_token")
        if not token:
            return None
        return create_delivery_notification(
            notification_type, title, body, order_id,
            owner="", owner_group=group_id,
            navigate_to_url=f"/delivery/guest/{order_id}?token={token}",
            guest_token=token,
        )
    user_id = assignment.get("user_id")
    if not user_id:
        return None
    return create_delivery_notification(
        notification_type, title, body, order_id,
        owner=str(user_id), owner_group=group_id,
        navigate_to_url=f"/deliveries/{order_id}",
    )


def _send_one(notification: Optional[Notification]) -> None:
    if notification is not None:
        send_notifications_batch([notification])


def fanout_delivery_assigned(*, order: Dict[str, Any], preparing: bool = False) -> None:
    body = f"Recoger en {_store_name(order)}, entregar a {_buyer_name(order)}"
    if preparing:
        body += ". Todavía se está preparando; te avisamos cuando esté lista"
    _send_one(_rider_notification(
        order.get("delivery_assignment"), order, NotificationType.DELIVERY_ASSIGNED,
        "Te asignaron una entrega", body,
    ))


def fanout_delivery_ready(*, order: Dict[str, Any]) -> None:
    """The store marked the order ready: the assigned rider can go and collect it."""
    _send_one(_rider_notification(
        order.get("delivery_assignment"), order, NotificationType.DELIVERY_READY,
        "Ya está lista",
        f"{_part_name(order)} en {_store_name(order)}. Pídele el código al encargado de la tienda.",
    ))


def fanout_delivery_time_changed(*, order: Dict[str, Any], previous_time: Any = None) -> None:
    assignment = order.get("delivery_assignment")
    if not assignment:
        return
    body = f"{_buyer_name(order)}: ahora a las {_local_hhmm(order.get('to_be_delivered_time'))}"
    if previous_time:
        body += f" (antes {_local_hhmm(previous_time)})"
    _send_one(_rider_notification(
        assignment, order, NotificationType.DELIVERY_TIME_CHANGED, "Cambió la hora de entrega", body,
    ))


def fanout_delivery_reassigned(*, order: Dict[str, Any], previous_assignment: Optional[Dict[str, Any]]) -> None:
    new_assignment = order.get("delivery_assignment")
    if not previous_assignment or not new_assignment:
        return
    _send_one(_rider_notification(
        previous_assignment, order, NotificationType.DELIVERY_REASSIGNED,
        "Te reasignaron",
        f"La orden de {_delivery_address(order)} pasó a {_rider_name(new_assignment)}. Ya no es tuya.",
    ))


def fanout_delivery_canceled(*, order: Dict[str, Any]) -> None:
    after_pickup = bool(order.get("picked_up_at"))
    _send_one(_rider_notification(
        order.get("delivery_assignment"), order, NotificationType.DELIVERY_CANCELED,
        "Cancelaron la orden",
        f"{_part_name(order)}, {_store_name(order)}. "
        + ("Devuélvela a la tienda." if after_pickup else "No la recojas."),
    ))


def fanout_issue_resolved(*, order: Dict[str, Any], action: str, resolution: Dict[str, Any]) -> None:
    """Someone acted on an open issue: the rider is told what to do now, and the party that did
    not act is told what changed (buyer fixed it -> store; store rescheduled -> buyer)."""
    role = (resolution.get("by") or {}).get("role")
    when = _local_hhmm(order.get("to_be_delivered_time"))
    rider_copy = {
        "fix_and_retry": ("Datos corregidos", "El comprador corrigió los datos. Intenta de nuevo."),
        "reschedule": ("Nuevo horario", f"Intenta de nuevo{f' a las {when}' if when else ''}."),
        "return_to_store": ("Devuelve el paquete", "Devuelve el paquete a la tienda."),
    }.get(action)
    if rider_copy:
        _send_one(_rider_notification(
            order.get("delivery_assignment"), order, NotificationType.DELIVERY_ISSUE_RESOLVED, *rider_copy,
        ))
    part = sentence_case(_part_name(order))
    when_label = local_time_label(order.get("to_be_delivered_time"))
    if action == "fix_and_retry" and role != "store":
        _notify_selling_group(
            order, NotificationType.DELIVERY_ISSUE_RESOLVED, f"{display_name(_buyer_name(order))} corrigió los datos",
            f"{part}: el repartidor lo intentará de nuevo.",
        )
    elif action in ("reschedule", "return_to_store") and role != "buyer":
        _notify_buyer_group(
            order, NotificationType.DELIVERY_ISSUE_RESOLVED, "Reprogramamos tu entrega",
            f"{part}: " + (f"llega a las {when_label}." if when_label and action == "reschedule" else "lo intentaremos de nuevo."),
        )


def _notify_selling_group(
    order: Dict[str, Any], notification_type: NotificationType, title: str, body: str,
    *, action: Optional[Dict[str, str]] = None, decision_key: Optional[str] = None,
) -> None:
    """Every user of the selling group except the assigned rider (seller roles, push included)."""
    group_id = _selling_group_id(order)
    if not group_id:
        return
    rider_uid = str((order.get("delivery_assignment") or {}).get("user_id") or "")
    order_id = _order_id(order)
    url = order_management_path(order_id, current_role=2)
    notifications: List[Notification] = []
    for group_found in _users_by_group_ids([group_id]):
        owner_group = str(group_found.get("_id") or group_id)
        for user_id in group_found.get("users") or []:
            if str(user_id) == rider_uid:
                continue
            notifications.append(create_delivery_notification(
                notification_type, title, body, order_id,
                owner=str(user_id), owner_group=owner_group, navigate_to_url=url,
                visible_roles=DELIVERY_SELLER_ROLES,
                side="sell", vehicle=_vehicle(order.get("part_request") or {}),
                action=action and {**action, "href": url}, decision_key=decision_key,
            ))
    if notifications:
        send_notifications_batch(notifications)


def fanout_delivery_handed_off(*, order: Dict[str, Any], unverified: bool = False) -> None:
    """The rider collected the order. Without the code, the store is asked to check the parcel."""
    rider = _rider_name(order.get("delivery_assignment") or {})
    when = local_time_label(order.get("picked_up_at"))
    part = sentence_case(_part_name(order))
    if unverified:
        _notify_selling_group(
            order, NotificationType.DELIVERY_HANDED_OFF, f"{rider} recogió sin código",
            f"{part} · revisa la foto del paquete.",
            action={"label": "Ver foto"}, decision_key=f"order:{_order_id(order)}:handoff",
        )
    else:
        _notify_selling_group(
            order, NotificationType.DELIVERY_HANDED_OFF, f"{rider} recogió un pedido",
            f"{part} · con código" + (f", {when}" if when else ""),
        )


def _notify_buyer_group(
    order: Dict[str, Any], notification_type: NotificationType, title: str, body: str,
    *, action: Optional[Dict[str, str]] = None, decision_key: Optional[str] = None,
) -> None:
    creator_group = str((order.get("part_request") or {}).get("creatorGroup") or "")
    if not creator_group:
        return
    order_id = _order_id(order)
    url = order_management_path(order_id, current_role=1)
    notifications: List[Notification] = []
    for group_found in _users_by_group_ids([creator_group]):
        owner_group = str(group_found.get("_id") or creator_group)
        for user_id in group_found.get("users") or []:
            notifications.append(create_delivery_notification(
                notification_type, title, body, order_id,
                owner=str(user_id), owner_group=owner_group, navigate_to_url=url,
                side="buy", vehicle=_vehicle(order.get("part_request") or {}),
                action=action and {**action, "href": url}, decision_key=decision_key,
            ))
    if notifications:
        send_notifications_batch(notifications)


def fanout_pickup_code_guessing(*, order_id: str) -> None:
    """The rider missed the pickup code too many times and it was retired: the store is told to
    check who is at the counter. The alert never contains the code."""
    from bson import ObjectId

    from app.repositories import OrderRepository as orderRepository

    if not ObjectId.is_valid(str(order_id)):
        return
    order = orderRepository.find_one({"_id": ObjectId(str(order_id))})
    if not order:
        return
    order = {**order, "_id": str(order["_id"])}
    _notify_selling_group(
        order, NotificationType.DELIVERY_ISSUE, "Código de recogida bloqueado",
        f"{sentence_case(_part_name(order))}: el repartidor falló el código muchas veces. "
        "Si es quien esperas, puede recoger con una foto.",
    )


def fanout_delivery_issue(*, order: Dict[str, Any], failure: Dict[str, Any]) -> None:
    """An attempt failed: the store is told (it can reschedule or return), and for a failed
    delivery the buyer is told too (they can fix the address, phone or time)."""
    reason = DELIVERY_FAILURE_REASON_TEXT.get(str(failure.get("reason") or ""), "otro motivo")
    note = (failure.get("note") or "").strip()
    if failure.get("reason") == "other" and note:
        reason = f"{reason} ({note})"
    pickup = failure.get("kind") == "pickup"
    title = "No se pudo recoger un pedido" if pickup else "No pudimos entregar un pedido"
    part = sentence_case(_part_name(order))
    key = f"order:{_order_id(order)}:issue:{failure.get('id')}" if failure.get("id") else None
    _notify_selling_group(order, NotificationType.DELIVERY_ISSUE, title, f"{part}: {reason}.",
                          action={"label": "Resolver"}, decision_key=key)
    if not pickup:
        _notify_buyer_group(
            order, NotificationType.DELIVERY_ISSUE, "No pudimos entregar tu pedido",
            f"{part}: {reason}.",
            action={"label": "Corregir datos"}, decision_key=key,
        )


def fanout_delivery_failed(*, order: Dict[str, Any], failure: Dict[str, Any]) -> None:
    """Seller side only: every user of the selling group except the assigned rider."""
    group_id = _selling_group_id(order)
    if not group_id:
        return
    reason = DELIVERY_FAILURE_REASON_TEXT.get(str(failure.get("reason") or ""), "otro motivo")
    note = (failure.get("note") or "").strip()
    if failure.get("reason") == "other" and note:
        reason = f"{reason} ({note})"
    rider_uid = str((order.get("delivery_assignment") or {}).get("user_id") or "")
    order_id = _order_id(order)
    title, body = "No pudimos entregar un pedido", f"{sentence_case(_part_name(order))}: {reason}."
    key = f"order:{order_id}:issue:{failure.get('id')}" if failure.get("id") else None
    url = order_management_path(order_id, current_role=2)

    notifications: List[Notification] = []
    for group_found in _users_by_group_ids([group_id]):
        owner_group = str(group_found.get("_id") or group_id)
        for user_id in group_found.get("users") or []:
            if str(user_id) == rider_uid:
                continue
            notifications.append(create_delivery_notification(
                NotificationType.DELIVERY_FAILED, title, body, order_id,
                owner=str(user_id), owner_group=owner_group, navigate_to_url=url,
                visible_roles=DELIVERY_SELLER_ROLES,
                side="sell", vehicle=_vehicle(order.get("part_request") or {}),
                action={"label": "Resolver", "href": url}, decision_key=key,
            ))
    if notifications:
        send_notifications_batch(notifications)
