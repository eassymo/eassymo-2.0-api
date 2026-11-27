"""The buyer changed a part after a store quoted it ("Mi oferta sigue igual" in the cotizador).

The store's offer carries `before_change` until the store either edits it or says it still stands; both clear the
flag. Only the store that quoted (or the call center that posted for it) can do this, as with withdrawing.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from bson import ObjectId
from fastapi import HTTPException

from app.repositories import OfferRepository as offerRepository
from app.services import OfferWithdrawalService

GONE = OfferWithdrawalService.GONE
NOT_YOURS = "Solo la tienda que cotizó puede cambiarla."


def confirm_current(offer_id: str, uid: str, group_id: str) -> Dict[str, Any]:
    if not ObjectId.is_valid(offer_id):
        raise HTTPException(status_code=404, detail=GONE)
    doc = offerRepository.find_offer_by_id(offer_id)
    if not doc:
        raise HTTPException(status_code=404, detail=GONE)
    if not OfferWithdrawalService._acting_for_offer(doc, uid, group_id):
        raise HTTPException(status_code=403, detail=NOT_YOURS)
    # The store may have withdrawn it, or the buyer removed the part, since it was read.
    if not offerRepository.confirm_current(offer_id, datetime.now(timezone.utc)):
        raise HTTPException(status_code=404, detail=GONE)
    return {"offer_id": offer_id, "before_change": False}
