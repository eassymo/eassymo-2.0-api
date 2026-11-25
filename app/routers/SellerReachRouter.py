"""Store view of the seller reach cap: today's wide slots, preview and per-request reach."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.dependencies import group_auth
from app.repositories import OfferRepository as offerRepository
from app.repositories import PartRequestRepository as partRequestRepository
from app.schemas.PartRequest import PartRequest
from app.schemas.SellerReach import PreviewIn
from app.services import SellerReachService as reach
from app.services import authz
from app.utils.ResponseUtils import error_json_response, get_successful_response

logger = logging.getLogger(__name__)

sellerReachRouter = APIRouter(prefix="/seller-reach", tags=["Seller Reach"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ok(body):
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(body))


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


@sellerReachRouter.get("/requests/{specific_order_uid}", description="Reach of each part of an order (creator group only)")
def get_request_reach(request: Request, specific_order_uid: str):
    try:
        uid = authz.caller_uid(request)
        docs = list(partRequestRepository.find_by_specific_order_uid(specific_order_uid))
        if not docs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitud no encontrada")
        group_auth.assert_group_membership(uid, str(docs[0]["creatorGroup"]))
        now = _now()
        parts, stores = [], set()
        for raw in docs:
            doc = PartRequest(**raw)
            part = doc.part or {}
            stores.update(i for i in [*(doc.subscribedSellers or []), *(doc.subscribedFollowers or [])] if i)
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
        responded = offerRepository.distinct("group_id", {"request_id": {"$in": [p["id"] for p in parts]}})
        return _ok(
            {
                "today": reach.today(str(docs[0]["creatorGroup"]), now),
                "audience_total": len(stores),
                "responded_total": len({g for g in responded if g}),
                "parts": parts,
            }
        )
    except HTTPException as e:
        return error_json_response(e)
