from typing import Dict, Any, List, Optional
from app.schemas.Notification import NotificationType, Notification
from app.schemas.Users import UserRoles
from app.utils.display_text import display_name, sentence_case, local_time_label


DEFAULT_ROLES = [
    UserRoles.ADMIN_BUYER_SHOP.value,
    UserRoles.ADMIN_SELLER_SHOP.value
]


def structured_notification(
    *,
    type: NotificationType,
    owner: str,
    owner_group: str,
    title: str,
    body: str,
    side: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    vehicle: str = "",
    action: Optional[Dict[str, str]] = None,
    decision_key: Optional[str] = None,
    visible_roles: Optional[List[str]] = None,
) -> Notification:
    """A v2 notice: title/body/side drive the screen and the push; message stays for older clients."""
    return Notification(
        type=type,
        message=f"{title}. {body}" if body else title,
        title=title,
        body=body or None,
        side=side,
        vehicle=vehicle or None,
        action=action,
        decision_key=decision_key,
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles if visible_roles is not None else DEFAULT_ROLES,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data,
    )


# ── Copy helpers ─────────────────────────────────────────────────────────────

def _money(price: Optional[float]) -> str:
    if price is None:
        return ""
    return f"${int(price):,}" if float(price).is_integer() else f"${price:,.2f}"


def _join(*parts: Optional[str]) -> str:
    return " · ".join(p for p in parts if p)


def _pieces(count: Optional[int]) -> str:
    if not count:
        return ""
    return f"{count} pieza" if count == 1 else f"{count} piezas"


# ── Builders ─────────────────────────────────────────────────────────────────
# Title = who did what in the reader's words (also the push title); body = the part and the datum
# that changed. Builders that need data the old call sites did not pass take it as keyword arguments
# and drop that part of the body when absent.

def create_part_request_notification(
    store_name: str,
    part_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    vehicle: str = "",
) -> Notification:
    return structured_notification(
        type=NotificationType.PART_REQUEST_CREATED,
        title=f"{display_name(store_name)} busca una pieza",
        body=sentence_case(part_name),
        side="sell", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_part_request_reminder_notification(
    store_name: str,
    part_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    request_id: Optional[str] = None,
    vehicle: str = "",
) -> Notification:
    request_id = request_id or meta_data.get("requestId")
    return structured_notification(
        type=NotificationType.PART_REQUEST_REMINDER,
        title=f"{display_name(store_name)} sigue esperando tu cotización",
        body=sentence_case(part_name),
        side="sell", vehicle=vehicle,
        action={"label": "Cotizar", "href": navigate_to_url},
        decision_key=f"request:{request_id}:quote:{owner_group}" if request_id else None,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_offer_workshop_approval(
    store_name: str,
    part_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    price: Optional[float] = None,
    vehicle: str = "",
    offer_id: Optional[str] = None,
) -> Notification:
    offer_id = offer_id or meta_data.get("offerId")
    return structured_notification(
        type=NotificationType.WORKSHOP_PENDING_APPROVAL,
        title="Una oferta espera tu aprobación",
        body=_join(sentence_case(part_name), _money(price), display_name(store_name)),
        side="buy", vehicle=vehicle,
        action={"label": "Revisar", "href": navigate_to_url},
        decision_key=f"offer:{offer_id}:approve" if offer_id else None,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_offer_notification(
    store_name: str,
    part_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    price: Optional[float] = None,
    vehicle: str = "",
) -> Notification:
    return structured_notification(
        type=NotificationType.OFFER_CREATED,
        title=f"Nueva oferta de {display_name(store_name)}",
        body=_join(sentence_case(part_name), _money(price)),
        side="buy", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_offer_selected_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    price: Optional[float] = None,
    vehicle: str = "",
) -> Notification:
    return structured_notification(
        type=NotificationType.OFFER_SELECTED,
        title=f"{display_name(store_name)} pidió tu oferta",
        body=f"{_join(sentence_case(part_name), _money(price))}. Confirma la hora de entrega.",
        side="sell", vehicle=vehicle,
        action={"label": "Confirmar hora", "href": navigate_to_url},
        decision_key=f"order:{order_id}:confirm" if order_id else None,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_offer_selected_by_commissioner_to_origin_group_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    price: Optional[float] = None,
    seller_name: str = "",
    vehicle: str = "",
) -> Notification:
    # store_name is the commissioner (kept for call sites); the seller is shown when known.
    return structured_notification(
        type=NotificationType.OFFER_SELECTED,
        title="Tu comisionado pidió una pieza",
        body=_join(sentence_case(part_name), _money(price), display_name(seller_name or store_name)),
        side="buy", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_order_confirmed_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    delivery_time: Any = None,
    vehicle: str = "",
) -> Notification:
    when = local_time_label(delivery_time)
    return structured_notification(
        type=NotificationType.ORDER_CONFIRMED,
        title=f"{display_name(store_name)} está preparando tu pedido",
        body=_join(sentence_case(part_name), f"llega {when}" if when else ""),
        side="buy", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_order_ready_to_be_sent_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    vehicle: str = "",
) -> Notification:
    return structured_notification(
        type=NotificationType.ORDER_READY_TO_BE_SENT,
        title="Tu pedido está listo para salir",
        body=_join(sentence_case(part_name), display_name(store_name)),
        side="buy", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_order_sent_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    rider_name: str = "",
    vehicle: str = "",
) -> Notification:
    return structured_notification(
        type=NotificationType.ORDER_SENT,
        title="Tu pedido va en camino",
        body=_join(sentence_case(part_name), f"con {rider_name}" if rider_name else ""),
        side="buy", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_order_received_notification(
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    buyer_name: str = "",
    received_at: Any = None,
    vehicle: str = "",
) -> Notification:
    """Goes to the selling store: the buyer already knows they received it."""
    who = display_name(buyer_name) or "Tu cliente"
    return structured_notification(
        type=NotificationType.ORDER_RECIEVED,
        title=f"{who} recibió su pedido",
        body=_join(sentence_case(part_name), local_time_label(received_at)),
        side="sell", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_order_delayed_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    delivery_time: Any = None,
    vehicle: str = "",
) -> Notification:
    when = local_time_label(delivery_time)
    return structured_notification(
        type=NotificationType.ORDER_DELAYED,
        title=f"{display_name(store_name)} retrasó tu pedido",
        body=_join(sentence_case(part_name), f"ahora llega {when}" if when else ""),
        side="buy", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_invite_accepted_notification(
    store_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    return structured_notification(
        type=NotificationType.INVITE_ACCEPTED,
        title=f"{display_name(store_name)} aceptó tu invitación",
        body="Ya está en tu red.",
        side=None,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_part_request_invite_notification(
    inviter_group_name: str,
    inviter_user: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    part_requests = meta_data.get("partRequests") or []
    vehicle = (part_requests[0].get("vehicleInformation") or {}) if part_requests else {}
    vehicle_text = " ".join(str(vehicle[key]) for key in ("maker", "model", "year") if vehicle.get(key))
    return structured_notification(
        type=NotificationType.PART_REQUEST_INVITE,
        title=f"{display_name(inviter_group_name)} te invita a cotizar",
        body=_join(_pieces(len(part_requests)), vehicle_text),
        side="sell", vehicle=vehicle_text,
        action={"label": "Ver invitación", "href": navigate_to_url},
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_callcenter_connected_group_selected_notification(
    invited_group_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    vehicle: str = "",
) -> Notification:
    part_description = (meta_data.get("partRequest") or {}).get("part", {}).get("tipoParteDescripcion", "")
    return structured_notification(
        type=NotificationType.CALLCENTER_CONNECTED_GROUP_SELECTED_FOR_REQUEST,
        title=f"{display_name(invited_group_name)} recibió una solicitud",
        body=f"{_join(sentence_case(part_description), vehicle)}. Cotiza por ellos.",
        side="sell", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_offer_approval_request_notification(
    call_center_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    part_name: str = "",
    price: Optional[float] = None,
    vehicle: str = "",
    offer_id: Optional[str] = None,
) -> Notification:
    offer_id = offer_id or meta_data.get("offerId")
    detail = _join(sentence_case(part_name), _money(price))
    return structured_notification(
        type=NotificationType.OFFER_APPROVAL_REQUEST,
        title=f"{display_name(call_center_name)} armó una oferta por ti",
        body=f"{detail}. Revísala antes de que la vea el comprador." if detail else "Revísala antes de que la vea el comprador.",
        side="sell", vehicle=vehicle,
        action={"label": "Revisar", "href": navigate_to_url},
        decision_key=f"offer:{offer_id}:approve" if offer_id else None,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_callcenter_offer_approval_approved_notification(
    group_name: str,
    part_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    vehicle: str = "",
) -> Notification:
    return structured_notification(
        type=NotificationType.CALLCENTER_OFFER_APPROVAL_APPROVED,
        title=f"{display_name(group_name)} aprobó tu oferta",
        body=_join(sentence_case(part_name), "ya la ve el comprador."),
        side="sell", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_mostrador_folio_shared_notification(
    store_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    piece_count: Optional[int] = None,
    vehicle: str = "",
) -> Notification:
    folio_id = meta_data.get("folioId")
    return structured_notification(
        type=NotificationType.MOSTRADOR_FOLIO_SHARED,
        title=f"{display_name(store_name)} te mandó una cotización",
        body=_join(_pieces(piece_count), vehicle),
        side="buy", vehicle=vehicle,
        action={"label": "Revisar", "href": navigate_to_url},
        decision_key=f"folio:{folio_id}:open" if folio_id else None,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_mostrador_folio_assigned_notification(
    store_name: str,
    piece_count: int,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    vehicle: str = "",
) -> Notification:
    if visible_roles is None:
        visible_roles = [UserRoles.ADMIN_BUYER_SHOP.value]
    folio_id = meta_data.get("folioId")
    return structured_notification(
        type=NotificationType.MOSTRADOR_FOLIO_ASSIGNED,
        title=f"{display_name(store_name)} te pasó una lista",
        body=_join(_pieces(piece_count), vehicle),
        side="buy", vehicle=vehicle,
        action={"label": "Revisar", "href": navigate_to_url},
        decision_key=f"folio:{folio_id}:open" if folio_id else None,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_mostrador_order_created_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    price: Optional[float] = None,
    vehicle: str = "",
) -> Notification:
    return structured_notification(
        type=NotificationType.MOSTRADOR_ORDER_CREATED,
        title=f"Pediste en el mostrador de {display_name(store_name)}",
        body=_join(sentence_case(part_name), _money(price)),
        side="buy", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_mostrador_option_added_notification(
    message: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    store_name: str = "",
    part_name: str = "",
    price: Optional[float] = None,
    vehicle: str = "",
) -> Notification:
    """Without the store and part (older activity-log entries) the free text becomes the body."""
    if not store_name:
        return structured_notification(
            type=NotificationType.MOSTRADOR_OPTION_ADDED,
            title="Hay una opción nueva en tu lista",
            body=message,
            side="buy", vehicle=vehicle,
            owner=owner, owner_group=owner_group, visible_roles=visible_roles,
            navigate_to_url=navigate_to_url, meta_data=meta_data,
        )
    return structured_notification(
        type=NotificationType.MOSTRADOR_OPTION_ADDED,
        title=f"{display_name(store_name)} agregó una opción",
        body=_join(sentence_case(part_name), _money(price)),
        side="buy", vehicle=vehicle,
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_mostrador_shop_invited_notification(
    inviter_name: str,
    piece_count: int,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None,
    *,
    vehicle: str = "",
) -> Notification:
    return structured_notification(
        type=NotificationType.MOSTRADOR_SHOP_INVITED,
        title=f"{display_name(inviter_name)} te invita a cotizar su lista",
        body=_join(_pieces(piece_count), vehicle),
        side="sell", vehicle=vehicle,
        action={"label": "Ver invitación", "href": navigate_to_url},
        owner=owner, owner_group=owner_group, visible_roles=visible_roles,
        navigate_to_url=navigate_to_url, meta_data=meta_data,
    )


def create_relationship_review_reminder(
    owner: str,
    owner_group: str,
) -> Notification:
    return structured_notification(
        type=NotificationType.RELATIONSHIP_REVIEW_REMINDER,
        title="Revisa tus relaciones",
        body="Mira con qué tiendas trabajas y a quién te falta responder.",
        side=None,
        owner=owner, owner_group=owner_group, visible_roles=DEFAULT_ROLES,
        navigate_to_url="/relaciones/inicio", meta_data={"source": "relationship_reminder"},
    )


# Dictionary mapping notification types to their creator functions
NOTIFICATION_CREATORS = {
    NotificationType.PART_REQUEST_CREATED: create_part_request_notification,
    NotificationType.OFFER_CREATED: create_offer_notification,
    NotificationType.OFFER_SELECTED: create_offer_selected_notification,
    NotificationType.ORDER_CONFIRMED: create_order_confirmed_notification,
    NotificationType.ORDER_READY_TO_BE_SENT: create_order_ready_to_be_sent_notification,
    NotificationType.ORDER_SENT: create_order_sent_notification,
    NotificationType.ORDER_RECIEVED: create_order_received_notification,
    NotificationType.ORDER_DELAYED: create_order_delayed_notification,
    NotificationType.INVITE_ACCEPTED: create_invite_accepted_notification,
    NotificationType.PART_REQUEST_INVITE: create_part_request_invite_notification,
    NotificationType.CALLCENTER_CONNECTED_GROUP_SELECTED_FOR_REQUEST: create_callcenter_connected_group_selected_notification,
    NotificationType.OFFER_APPROVAL_REQUEST: create_offer_approval_request_notification,
    NotificationType.CALLCENTER_OFFER_APPROVAL_APPROVED: create_callcenter_offer_approval_approved_notification,
    NotificationType.WORKSHOP_PENDING_APPROVAL: create_offer_workshop_approval,
    NotificationType.OFFER_SELECTED_BY_COMMISSIONER_TO_ORIGIN_GROUP: create_offer_selected_by_commissioner_to_origin_group_notification,
    NotificationType.MOSTRADOR_FOLIO_SHARED: create_mostrador_folio_shared_notification,
    NotificationType.MOSTRADOR_FOLIO_ASSIGNED: create_mostrador_folio_assigned_notification,
    NotificationType.MOSTRADOR_ORDER_CREATED: create_mostrador_order_created_notification,
    NotificationType.MOSTRADOR_OPTION_ADDED: create_mostrador_option_added_notification,
    NotificationType.MOSTRADOR_SHOP_INVITED: create_mostrador_shop_invited_notification,
    NotificationType.RELATIONSHIP_REVIEW_REMINDER: create_relationship_review_reminder,
}

# ── Deliveries ───────────────────────────────────────────────────────────────
# Rider alerts (assigned / time changed / reassigned / canceled) and the seller's
# "failed" alert. The message is "Title. Body" so push and the bell show it whole;
# metaData keeps title and body apart for the deliveries feed.

DELIVERY_SELLER_ROLES = [UserRoles.ADMIN_SELLER_SHOP.value, UserRoles.SELLER_SHOP.value]


def create_delivery_notification(
    notification_type: NotificationType,
    title: str,
    body: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    guest_token: Optional[str] = None,
    visible_roles: Optional[List[str]] = None,
) -> Notification:
    return Notification(
        type=notification_type,
        message=f"{title}. {body}",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData={"orderId": order_id, "title": title, "body": body},
        guest_token=guest_token,
    )
