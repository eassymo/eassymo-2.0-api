"""Server-side notification fan-out (ADR-001 Phase 4)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.factories.NotificationsCreator import (
    create_callcenter_connected_group_selected_notification,
    create_callcenter_offer_approval_approved_notification,
    create_invite_accepted_notification,
    create_offer_approval_request_notification,
    create_offer_notification,
    create_offer_selected_notification,
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
from app.schemas.Notification import Notification, NotificationType
from app.schemas.Offer import OfferStatus
from app.schemas.Order import OrderStatus
from app.services import CallCenterService as callCenterService
from app.services import GroupService as groupService
from app.utils.notification_routes import (
    buyer_offer_review_path,
    order_management_v2_path,
    seller_offer_creator_path,
    buyer_offer_notification_meta,
)
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


def _users_by_group_ids(group_ids: List[str]) -> List[Dict[str, Any]]:
    if not group_ids:
        return []
    return groupService.find_users_by_groups_ids_v2(group_ids)


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

        for group_found in users_from_groups:
            group_id = str(group_found.get("_id") or "")
            for user_id in group_found.get("users") or []:
                notifications.append(
                    create_part_request_notification(
                        store_name=creator_group_name,
                        part_name=part_name,
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
        for cc_user in callcenter_users:
            invited_group_name = group_names.get(str(cc_user.get("group_id") or ""), "")
            if not invited_group_name:
                continue
            notifications.append(
                create_callcenter_connected_group_selected_notification(
                    invited_group_name=invited_group_name,
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
    navigate_to_url = order_management_v2_path(order_id, current_role=2)
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
    navigate_to_url = order_management_v2_path(order_id, current_role=1)
    meta_data = {"orderId": order_id}

    notification = create_order_delayed_notification(
        store_name=store_name or "Tienda",
        part_name=part_name,
        order_id=order_id,
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
    part_request: Dict[str, Any],
) -> None:
    notification = create_part_request_invite_notification(
        inviter_group_name=inviter_group_name,
        inviter_user=inviter_user,
        owner=owner,
        owner_group=owner_group,
        navigate_to_url=f"/join-request-invite/{invite_id}",
        meta_data={"partRequest": part_request},
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

    current_role = 2 if status_enum == OrderStatus.RECIEVED else 1
    navigate_to_url = order_management_v2_path(order_id, current_role=current_role)
    meta_data = {"orderId": order_id}

    notifications: List[Notification] = []
    for group_found in _users_by_group_ids([creator_group]):
        group_id = str(group_found.get("_id") or creator_group)
        for user_id in group_found.get("users") or []:
            owner = str(user_id)
            if notif_type == NotificationType.ORDER_CONFIRMED:
                notifications.append(
                    create_order_confirmed_notification(
                        store_name=store_name,
                        part_name=part_name,
                        order_id=order_id,
                        owner=owner,
                        owner_group=group_id,
                        navigate_to_url=navigate_to_url,
                        meta_data=meta_data,
                    )
                )
            elif notif_type == NotificationType.ORDER_READY_TO_BE_SENT:
                notifications.append(
                    create_order_ready_to_be_sent_notification(
                        store_name=store_name,
                        part_name=part_name,
                        order_id=order_id,
                        owner=owner,
                        owner_group=group_id,
                        navigate_to_url=navigate_to_url,
                        meta_data=meta_data,
                    )
                )
            elif notif_type == NotificationType.ORDER_SENT:
                notifications.append(
                    create_order_sent_notification(
                        store_name=store_name,
                        part_name=part_name,
                        order_id=order_id,
                        owner=owner,
                        owner_group=group_id,
                        navigate_to_url=navigate_to_url,
                        meta_data=meta_data,
                    )
                )
            elif notif_type == NotificationType.ORDER_RECIEVED:
                notifications.append(
                    create_order_received_notification(
                        part_name=part_name,
                        order_id=order_id,
                        owner=owner,
                        owner_group=group_id,
                        navigate_to_url=navigate_to_url,
                        meta_data=meta_data,
                    )
                )

    if notifications:
        send_notifications_batch(notifications)
