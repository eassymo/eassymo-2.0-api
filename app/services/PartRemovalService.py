"""The buyer removes one part of a request ("Quitar pieza").

Every offer on the part moves whole to OffersArchive with who, when and its previous status (never hard-deleted), the
part goes inactive with who removed it, and each store that had an offer on it gets one notice per user. A part that
was already ordered can't be removed. Removing it again changes nothing, so a double tap or a retry is safe:
a request first claims the part (`removing`); one that loses the claim changes nothing and answers 200 only if the
part is already removed (409 while the other is still at it). A failed removal releases its claim so the retry
archives again (an upsert) and reports every offer archived for the part.

A request keeps at least one part: once the claim is held, a removal that would leave no live part answers 409. Other
parts that are being removed right now don't count as staying, so two removals of a request's last two parts can't
both succeed.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from bson import ObjectId
from fastapi import HTTPException

from app.factories.NotificationsCreator import create_part_removed_notification
from app.repositories import GroupRepository as groupRepository
from app.repositories import OfferArchiveRepository as offerArchiveRepository
from app.repositories import OfferRepository as offerRepository
from app.repositories import PartRequestRepository as partRequestRepository
from app.services import GroupService as groupService
from app.services import NotificationService, OfferWithdrawalService, authz
from app.utils.display_text import vehicle_label
from app.utils.notification_routes import seller_offer_creator_path
from app.utils.notifications import send_notifications_batch

logger = logging.getLogger(__name__)

GONE = "Esta pieza ya no existe."
NOT_CREATOR = "Solo quien creó la solicitud puede quitar piezas."
ORDERED = "Ya pediste esta pieza. Para quitarla, cancela el pedido primero."
IN_PROGRESS = "Esta pieza se está quitando. Intenta de nuevo en un momento."
LAST_PART = "Una solicitud necesita al menos una pieza."

REASON = "part_removed"
# A removal claim this old belongs to a request that died midway; another request may take it over.
STALE_CLAIM = timedelta(minutes=2)


def _user_in_group(uid: str, group_id: str) -> bool:
    return authz.is_member(uid, group_id)


def _result(part_request_id: str, offer_ids: List[str], group_ids: List[str]) -> Dict[str, Any]:
    return {"_id": part_request_id, "discarded_offer_ids": offer_ids, "notified_group_ids": group_ids}


def has_live_order(part_request_id: str) -> bool:
    """An order not canceled holds one of the part's offers."""
    return _any_live_order(list(offerRepository.find({"request_id": part_request_id})))


def _any_live_order(offers: List[Dict[str, Any]]) -> bool:
    return any(OfferWithdrawalService._has_live_order(str(offer["_id"])) for offer in offers)


def remove(part_request_id: str, uid: str, group_id: str) -> Dict[str, Any]:
    """`group_id` is the store the caller acts for (where the grant was checked); the part must be that store's."""
    if not ObjectId.is_valid(part_request_id):
        raise HTTPException(status_code=404, detail=GONE)
    part = partRequestRepository.find_one_by_id(part_request_id)
    if not part:
        raise HTTPException(status_code=404, detail=GONE)
    if str(part.get("creatorGroup") or "") != group_id or not _user_in_group(uid, group_id):
        raise HTTPException(status_code=403, detail=NOT_CREATOR)
    if part.get("removed"):
        return _result(part_request_id, [], [])

    now = datetime.now(timezone.utc)
    if not partRequestRepository.claim_removal(part_request_id, uid, now, now - STALE_CLAIM):
        # Another request holds the claim. Only a finished removal may be reported as done: that one may still be
        # running, fail (409, lost connection) or have died without releasing its claim.
        if (partRequestRepository.find_one_by_id(part_request_id) or {}).get("removed"):
            return _result(part_request_id, [], [])
        raise HTTPException(status_code=409, detail=IN_PROGRESS)
    try:
        _keep_one_part(part, now)
        discarded = _discard_offers(part_request_id, uid, now)
        partRequestRepository.edit_part_request(
            part_request_id, {"isActive": False, "removed": {"by": uid, "at": now}, "updatedAt": now})
    except Exception:
        partRequestRepository.release_removal(part_request_id, uid, now)
        raise

    group_ids = list(dict.fromkeys(str(offer["group_id"]) for offer in discarded if offer.get("group_id")))
    _settle_and_notify(part, part_request_id, discarded, group_ids)
    return _result(part_request_id, [str(offer["_id"]) for offer in discarded], group_ids)


def _keep_one_part(part: Dict[str, Any], now: datetime) -> None:
    """Run while holding the claim: another part must stay. A part someone else is removing now doesn't count."""
    live, free = partRequestRepository.count_live_others(part, now - STALE_CLAIM)
    if not free:
        raise HTTPException(status_code=409, detail=IN_PROGRESS if live else LAST_PART)


def _discard_offers(part_request_id: str, uid: str, now: datetime) -> List[Dict[str, Any]]:
    """Archive and delete the part's offers; returns every offer archived for the part, including those an earlier,
    failed attempt already archived."""
    offers = list(offerRepository.find({"request_id": part_request_id}))
    # Checked after the claim, so an order placed while the confirm sheet was open still blocks.
    if _any_live_order(offers):
        raise HTTPException(status_code=409, detail=ORDERED)
    # Archive first: if anything fails after this, every offer still exists somewhere.
    for offer in offers:
        offerArchiveRepository.upsert({
            **offer,
            "discard": {"by": uid, "at": now, "reason": REASON, "previous_status": OfferWithdrawalService._status(offer)},
        })
    if offers:
        offerRepository.delete_many({"_id": {"$in": [offer["_id"] for offer in offers]}})
    return offerArchiveRepository.find({"request_id": part_request_id, "discard.reason": REASON})


def _settle_and_notify(part: Dict[str, Any], part_request_id: str, offers: List[Dict[str, Any]],
                       group_ids: List[str]) -> None:
    """The part is already gone; a failure here must not undo or fail the removal."""
    try:
        NotificationService.resolve_decisions_prefix(f"request:{part_request_id}:quote:")
    except Exception:
        logger.exception("Could not resolve quote decisions for removed part %s", part_request_id)
    if not group_ids:
        return
    try:
        send_notifications_batch(_notifications(part, part_request_id, offers, group_ids))
    except Exception:
        logger.exception("Could not notify stores about removed part %s", part_request_id)


def _notifications(part: Dict[str, Any], part_request_id: str, offers: List[Dict[str, Any]],
                   group_ids: List[str]) -> list:
    store_name = (groupRepository.find_by_id(str(part.get("creatorGroup") or "")) or {}).get("name") or "Comprador"
    part_name = (part.get("part") or {}).get("tipoParteDescripcion") or "pieza"
    vehicle = vehicle_label(part.get("vehicleInformation"))
    navigate_to_url = seller_offer_creator_path(part_request_id)
    offers_by_group: Dict[str, List[Dict[str, Any]]] = {}
    for offer in offers:
        offers_by_group.setdefault(str(offer.get("group_id") or ""), []).append(offer)

    notifications = []
    for group in groupService.find_users_by_groups_ids_v2(group_ids):
        group_id = str(group.get("_id") or "")
        own = offers_by_group.get(group_id) or []
        for user_id in group.get("users") or []:
            notifications.append(create_part_removed_notification(
                store_name=store_name,
                part_name=part_name,
                owner=str(user_id),
                owner_group=group_id,
                navigate_to_url=navigate_to_url,
                meta_data={"requestId": part_request_id},
                offer_count=len(own),
                price=own[0].get("price") if len(own) == 1 else None,
                vehicle=vehicle,
            ))
    return notifications
