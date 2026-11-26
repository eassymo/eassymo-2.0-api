"""A store takes back one of its offers on a part ("Eliminar opción" in the cotizador).

The offer moves whole from Offers to OffersArchive with who, when and its previous status, so every reader of Offers
stops seeing it and nothing is lost. Only a draft (never sent) can come back, which is what Deshacer does.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from bson import ObjectId
from fastapi import HTTPException

from app.repositories import OfferArchiveRepository as offerArchiveRepository
from app.repositories import OfferRepository as offerRepository
from app.repositories import OrderRepository as orderRepository
from app.schemas.Offer import Offer, OfferStatus
from app.services import PickupCodeService

WITHDRAWABLE = frozenset({OfferStatus.pending_changes.value, OfferStatus.created.value})
WAITING_APPROVAL = frozenset({OfferStatus.pending_approval.value, OfferStatus.workshop_approval_pending.value})

GONE = "Esta opción ya no existe."
NOT_YOURS = "Solo la tienda que cotizó puede eliminarla."
ORDERED = "El comprador ya la pidió. Si no puedes surtirla, cancela desde la orden."
WAITING = "Esta opción espera aprobación; todavía no se puede eliminar."
CHANGED = "Esta opción cambió; vuelve a abrirla."
NO_UNDO = "Esta opción ya no se puede recuperar."


def _user_in_group(uid: str, group_id: str) -> bool:
    return PickupCodeService._user_in_group(uid, group_id)


def _acting_for_offer(doc: Dict[str, Any], uid: str, group_id: str) -> bool:
    """The store the caller acts as (where offers.edit was checked) must own the offer, or be the call center that
    posted it, and the caller must belong to that store."""
    owners = {str(doc.get("group_id") or "")}
    call_center = (doc.get("call_center_that_posted_offer") or {}).get("_id")
    if call_center:
        owners.add(str(call_center))
    return bool(group_id) and group_id in owners and _user_in_group(uid, group_id)


def _status(doc: Dict[str, Any]) -> str:
    status = doc.get("status")
    return status.value if isinstance(status, OfferStatus) else str(status or "")


def _has_live_order(offer_id: str) -> bool:
    ids = [offer_id]
    if ObjectId.is_valid(offer_id):
        ids.append(ObjectId(offer_id))
    return orderRepository.find_one({"offer._id": {"$in": ids}, "status": {"$ne": "CANCELED"}}) is not None


def withdraw(offer_id: str, uid: str, group_id: str) -> Dict[str, Any]:
    if not ObjectId.is_valid(offer_id):
        raise HTTPException(status_code=404, detail=GONE)
    doc = offerRepository.find_offer_by_id(offer_id)
    if not doc:
        raise HTTPException(status_code=404, detail=GONE)
    if not _acting_for_offer(doc, uid, group_id):
        raise HTTPException(status_code=403, detail=NOT_YOURS)

    status = _status(doc)
    if status == OfferStatus.selected.value or _has_live_order(offer_id):
        raise HTTPException(status_code=409, detail=ORDERED)
    if status not in WITHDRAWABLE:
        raise HTTPException(status_code=409, detail=WAITING if status in WAITING_APPROVAL else CHANGED)

    # Archive first: if anything fails after this, the offer still exists somewhere.
    offerArchiveRepository.insert({
        **doc,
        "withdrawal": {"by": uid, "at": datetime.now(timezone.utc), "previous_status": status},
    })
    if not offerRepository.delete_if_status(offer_id, status):
        offerArchiveRepository.delete(offer_id)
        raise HTTPException(status_code=409, detail=CHANGED)

    return {
        "offer_id": offer_id,
        "request_id": str(doc.get("request_id") or ""),
        "previous_status": status,
        "can_undo": status == OfferStatus.pending_changes.value,
    }


def restore(offer_id: str, uid: str, group_id: str) -> Dict[str, Any]:
    if not ObjectId.is_valid(offer_id):
        raise HTTPException(status_code=404, detail=GONE)
    archived = offerArchiveRepository.find_by_id(offer_id)
    if not archived:
        raise HTTPException(status_code=404, detail=GONE)
    if not _acting_for_offer(archived, uid, group_id):
        raise HTTPException(status_code=403, detail=NOT_YOURS)
    if (archived.get("withdrawal") or {}).get("previous_status") != OfferStatus.pending_changes.value:
        raise HTTPException(status_code=409, detail=NO_UNDO)

    doc = {k: v for k, v in archived.items() if k != "withdrawal"}
    offerRepository.insert_with_id(doc)
    offerArchiveRepository.delete(offer_id)
    return Offer(**doc).toJson()
