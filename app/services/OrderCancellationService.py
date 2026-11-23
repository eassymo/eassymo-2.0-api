"""The selling store backs out of an order while the part is still at the store.

The order flips to CANCELED with one conditional update (so two members acting at once cannot both win),
and only then does the buyer's request reopen and the notices go out.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, get_args

from bson import ObjectId
from fastapi import HTTPException

from app.repositories import GroupRepository as groupRepository
from app.repositories import OfferRepository as offerRepository
from app.repositories import OrderRepository as orderRepository
from app.repositories import PartRequestRepository as partRequestRepository
from app.repositories import RequestStatusByGroupRepository as requestStatusByGroupRepository
from app.schemas.Offer import OfferStatus
from app.schemas.Order import CancelReason, Order, OrderCancellation, OrderStatus
from app.schemas.RequestStatusByGroup import RequestStatusByGroup
from app.services import NotificationService, PickupCodeService, notification_fanout
from app.utils.display_text import display_name

logger = logging.getLogger(__name__)

SELLER_CANCELABLE = frozenset({
    OrderStatus.WAITING_FOR_CONFIRMATION,
    OrderStatus.CONFIRMED,
    OrderStatus.READY_TO_BE_DISPATCHED,
    OrderStatus.WAITING_FOR_COLLECTION,
    OrderStatus.WAITING_FOR_CUSTOMER_PICKUP,
})
NOTE_MAX = 200
LEFT_THE_STORE = "La pieza ya salió de la tienda."


def _user_in_group(uid: Optional[str], group_id: Optional[str]) -> bool:
    return PickupCodeService._user_in_group(uid, group_id)


def _alert(name: str, oid: Any, **kwargs) -> None:
    try:
        getattr(notification_fanout, name)(**kwargs)
    except Exception as exc:
        logger.warning("cancel alert %s failed for order %s: %s", name, oid, type(exc).__name__)


def _validate(reason: str, note: Optional[str]) -> Optional[str]:
    if reason not in get_args(CancelReason):
        raise HTTPException(status_code=422, detail="Motivo no válido.")
    clean = (note or "").strip()
    if len(clean) > NOTE_MAX:
        raise HTTPException(status_code=422, detail=f"La nota no puede pasar de {NOTE_MAX} caracteres.")
    return clean or None


def _mark_group_without_stock(group_id: str, request_id: str) -> None:
    existing = requestStatusByGroupRepository.find_by_group_and_request_id(group_id, request_id)
    if existing is not None:
        existing.status = OfferStatus.no_inventory
        requestStatusByGroupRepository.update(existing.id, existing)
    else:
        requestStatusByGroupRepository.insert(
            RequestStatusByGroup(group_id=group_id, request_id=request_id, status=OfferStatus.no_inventory))


def cancel_by_seller(order_id: str, uid: str, reason: str, note: Optional[str]) -> Dict[str, Any]:
    clean_note = _validate(reason, note)
    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found")
    docs = list(orderRepository.find_by_id(oid))
    if not docs:
        raise HTTPException(status_code=404, detail="Order not found")
    doc = docs[0]

    if doc.get("origin") == "mostrador":
        raise HTTPException(status_code=409, detail="Las órdenes de mostrador se cancelan desde el mostrador.")
    offer = doc.get("offer") or {}
    seller_group = str(offer.get("group_id") or "")
    if not _user_in_group(uid, seller_group):
        raise HTTPException(status_code=403, detail="Solo la tienda que vende puede cancelar esta orden.")

    status = doc.get("status")
    status = status.value if isinstance(status, OrderStatus) else status
    if status == OrderStatus.CANCELED.value:
        raise HTTPException(status_code=409, detail="Esta orden ya fue cancelada.")
    if status not in {s.value for s in SELLER_CANCELABLE}:
        raise HTTPException(status_code=409, detail=LEFT_THE_STORE)

    cancellation = OrderCancellation(by="seller", group_id=seller_group, user_id=uid, reason=reason,
                                     note=clean_note, at=datetime.now(timezone.utc))
    order = Order(**doc)
    order.change_status("CANCELED")
    order_json = order.toJson()
    request_id = str((doc.get("part_request") or {}).get("_id") or offer.get("request_id"))
    offer_group = groupRepository.find_by_id(seller_group) or {}
    last_cancellation = {
        "order_id": str(oid),
        "store_group_id": seller_group,
        "store_name": display_name(offer_group.get("name")),
        "reason": reason,
        "note": clean_note,
        "at": cancellation.at,
    }
    # Only the status we just read may be canceled: if a teammate moved it meanwhile, we lose and change nothing.
    updated = orderRepository.cancel_if_status(oid, [status], {
        "status": order_json["status"],
        "status_history": order_json["status_history"],
        "updated_at": order_json["updated_at"],
        "cancellation": cancellation.model_dump(),
        # the order carries a snapshot of its request; the buyer's Comprando reads the cancel from it
        "part_request.last_cancellation": last_cancellation,
        "part_request.isActive": True,
    })
    if updated is None:
        raise HTTPException(status_code=409, detail=LEFT_THE_STORE)

    offer_id = offer.get("_id")
    offerRepository.edit_offer(str(offer_id), {"status": OfferStatus.no_inventory.value})
    _mark_group_without_stock(seller_group, request_id)

    partRequestRepository.edit_part_request(request_id, {
        "status": "Created",
        "isActive": True,
        "last_cancellation": last_cancellation,
    })
    PickupCodeService.delete_code(str(oid))

    result = Order(**updated).toJson()
    if doc.get("delivery_assignment"):
        # the rider's copy keeps the assignment so the alert can say whether to return the part
        _alert("fanout_delivery_canceled", oid, order={**result, "delivery_assignment": doc["delivery_assignment"]})
    try:
        NotificationService.resolve_decisions(f"order:{oid}:confirm")
    except Exception as exc:
        logger.warning("resolve decisions failed for order %s: %s", oid, type(exc).__name__)
    remaining = len(list(offerRepository.find(
        {"request_id": request_id, "status": {"$in": [OfferStatus.created.value, OfferStatus.pending_approval.value]}})))
    _alert("fanout_order_canceled", oid, order=result, remaining_offers=remaining)
    return result
