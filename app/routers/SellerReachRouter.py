"""Store view of the seller reach cap: today's wide slots, preview and per-request reach."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.dependencies import group_auth
from app.repositories import OfferRepository as offerRepository
from app.repositories import PartRequestRepository as partRequestRepository
from app.schemas.Offer import OfferStatus
from app.schemas.PartRequest import PartRequest
from app.schemas.SellerReach import PreviewIn
from app.services import RequestRecipientsService as recipientsService
from app.services import SellerReachService as reach
from app.services import authz
from app.utils.ResponseUtils import error_json_response, get_successful_response

logger = logging.getLogger(__name__)

sellerReachRouter = APIRouter(prefix="/seller-reach", tags=["Seller Reach"])

# Offers the buyer can see. Pending_Changes drafts and No_Inventory are not answers (withdrawn offers leave Offers).
_VISIBLE_OFFER_STATUSES = [OfferStatus.created.value, OfferStatus.selected.value]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ok(body):
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(body))


def _order_parts(request: Request, specific_order_uid: str) -> list:
    """The order's part requests, for members of its creator group only (404 / 403 otherwise)."""
    uid = authz.caller_uid(request)
    docs = list(partRequestRepository.find_by_specific_order_uid(specific_order_uid))
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitud no encontrada")
    group_auth.assert_group_membership(uid, str(docs[0]["creatorGroup"]))
    return docs


@sellerReachRouter.get("/today", description="Wide slots the store has left today")
def get_today(request: Request, group_id: str = Query(...)):
    try:
        group_auth.assert_group_membership(authz.caller_uid(request), group_id)
        return _ok(reach.today(group_id, _now()))
    except HTTPException as e:
        return error_json_response(e)


@sellerReachRouter.post("/preview", description="Each part's audience against today's limits")
def preview(request: Request, payload: PreviewIn):
    try:
        group_auth.assert_group_membership(authz.caller_uid(request), payload.group_id)
        return _ok(reach.preview(payload, _now()))
    except HTTPException as e:
        return error_json_response(e)


@sellerReachRouter.get(
    "/requests/{specific_order_uid}/recipients",
    description="Stores that received an order, one entry per store (creator group only)",
)
def get_request_recipients(request: Request, specific_order_uid: str):
    try:
        docs = _order_parts(request, specific_order_uid)
        return _ok(recipientsService.recipients([PartRequest(**raw) for raw in docs]))
    except HTTPException as e:
        return error_json_response(e)


@sellerReachRouter.get("/requests/{specific_order_uid}", description="Reach of each part of an order (creator group only)")
def get_request_reach(request: Request, specific_order_uid: str):
    try:
        docs = _order_parts(request, specific_order_uid)
        now = _now()
        parts, stores = [], set()
        for raw in docs:
            doc = PartRequest(**raw)
            part = doc.part or {}
            stores.update(recipientsService.part_stores(doc))  # same rule as the recipients list
            parts.append(
                {
                    "id": doc.id,
                    "name": part.get("tipoParteDescripcion"),
                    "amount": part.get("amount"),
                    "unit": part.get("unitOfMeasure"),
                    "audience": reach.audience(doc.subscribedSellers, doc.subscribedFollowers),
                    "tier": (doc.reach or {}).get("tier"),
                    "room": reach.room(doc, now),
                }
            )
        offers = list(
            offerRepository.find(
                {"request_id": {"$in": [p["id"] for p in parts]}, "status": {"$in": _VISIBLE_OFFER_STATUSES}},
                {"group_id": 1, "price": 1},
            )
        )
        prices = [o["price"] for o in offers if o.get("price") is not None]
        return _ok(
            {
                "today": reach.today(str(docs[0]["creatorGroup"]), now),
                "audience_total": len(stores),
                "responded_total": len({o.get("group_id") for o in offers if o.get("group_id")}),
                "offers_total": len(offers),
                "lowest_price": min(prices, default=None),
                "parts": parts,
            }
        )
    except HTTPException as e:
        return error_json_response(e)
