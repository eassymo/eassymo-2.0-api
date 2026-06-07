from typing import Dict, Any, List, Optional
from app.schemas.Notification import NotificationType, Notification
from app.schemas.Users import UserRoles


DEFAULT_ROLES = [
    UserRoles.ADMIN_BUYER_SHOP.value,
    UserRoles.ADMIN_SELLER_SHOP.value
]


def create_part_request_notification(
    store_name: str,
    part_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.PART_REQUEST_CREATED,
        message=f"El {store_name} está buscando {part_name} pieza. Envía tu mejor oferta y sorpréndelos con tu servicio.",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )

def create_offer_workshop_approval(
    store_name: str,
    part_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES

    return Notification(
        type=NotificationType.WORKSHOP_PENDING_APPROVAL,
        message=f"El {store_name} acaba de ofertar para tu {part_name}. aprueba la pieza para su revisión por el comisionado",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )

def create_offer_notification(
    store_name: str,
    part_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.OFFER_CREATED,
        message=f"El {store_name} acaba de ofertar para tu {part_name}.",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )


def create_offer_selected_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.OFFER_SELECTED,
        message=f"Felicidades {store_name} ordenó tu oferta de la pieza {part_name}. Pedido núm: {order_id}.",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )

def create_offer_selected_by_commissioner_to_origin_group_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.OFFER_SELECTED,
        message=f"El comisionado {store_name} ordenó la oferta de la pieza {part_name}. Pedido núm: {order_id}.",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )


def create_order_confirmed_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.ORDER_CONFIRMED,
        message=f"El negocio {store_name} está preparando tu pieza {part_name}. Pedido núm {order_id}",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )


def create_order_ready_to_be_sent_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.ORDER_READY_TO_BE_SENT,
        message=f"El negocio {store_name} reporta que tu pieza {part_name} está lista para envío. Pedido núm {order_id}",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )


def create_order_sent_notification(
    store_name: str,
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.ORDER_SENT,
        message=f"El negocio {store_name} reporta que tu pieza {part_name} está en ruta. Pedido núm {order_id}",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )


def create_order_received_notification(
    part_name: str,
    order_id: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.ORDER_RECIEVED,
        message=f"Pieza {part_name} recibida por el comprador. Pedido núm {order_id}",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )


def create_invite_accepted_notification(
    store_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.INVITE_ACCEPTED,
        message=f"¡{store_name} ha aceptado tu invitación! Ahora podrás conectar y hacer negocios juntos en la red de eassymo.",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
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
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    part_description = meta_data.get("partRequest", {}).get("part", {}).get("tipoParteDescripcion", "")
    
    return Notification(
        type=NotificationType.PART_REQUEST_INVITE,
        message=f"¡{inviter_group_name} Te está invitando a ofertar en su solicitud por un {part_description}.",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )


def create_callcenter_connected_group_selected_notification(
    invited_group_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    part_description = meta_data.get("partRequest", {}).get("part", {}).get("tipoParteDescripcion", "")
    
    return Notification(
        type=NotificationType.CALLCENTER_CONNECTED_GROUP_SELECTED_FOR_REQUEST,
        message=f"¡El grupo {invited_group_name} ha sido invitado a ofertar en su solicitud por un {part_description}.",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        read=False,
        metaData=meta_data
    )


def create_offer_approval_request_notification(
    call_center_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.OFFER_APPROVAL_REQUEST,
        message=f"¡El Call Center {call_center_name} ha enviado una oferta para aprobación!",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        metaData=meta_data,
        read=False
    )


def create_callcenter_offer_approval_approved_notification(
    group_name: str,
    part_name: str,
    owner: str,
    owner_group: str,
    navigate_to_url: str,
    meta_data: Dict[str, Any],
    visible_roles: Optional[List[str]] = None
) -> Notification:
    if visible_roles is None:
        visible_roles = DEFAULT_ROLES
    
    return Notification(
        type=NotificationType.CALLCENTER_OFFER_APPROVAL_APPROVED,
        message=f"¡El grupo {group_name}, ha aceptado tu oferta para {part_name}!",
        owner=owner,
        ownerGroup=owner_group,
        visibleRoles=visible_roles,
        navigateToUrl=navigate_to_url,
        metaData=meta_data,
        read=False
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
    NotificationType.INVITE_ACCEPTED: create_invite_accepted_notification,
    NotificationType.PART_REQUEST_INVITE: create_part_request_invite_notification,
    NotificationType.CALLCENTER_CONNECTED_GROUP_SELECTED_FOR_REQUEST: create_callcenter_connected_group_selected_notification,
    NotificationType.OFFER_APPROVAL_REQUEST: create_offer_approval_request_notification,
    NotificationType.CALLCENTER_OFFER_APPROVAL_APPROVED: create_callcenter_offer_approval_approved_notification,
    NotificationType.WORKSHOP_PENDING_APPROVAL: create_offer_workshop_approval,
    NotificationType.OFFER_SELECTED_BY_COMMISSIONER_TO_ORIGIN_GROUP: create_offer_selected_by_commissioner_to_origin_group_notification
}