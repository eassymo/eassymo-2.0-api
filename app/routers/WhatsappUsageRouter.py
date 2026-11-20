"""Seller/manager view of the store's WhatsApp usage limits."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.authz import grant_keys as g
from app.repositories import GroupRepository as groupRepository
from app.repositories import UserRepository as userRepository
from app.repositories import WhatsappUsageRepository as usage_repo
from app.schemas.WhatsappUsage import CreditRequestIn
from app.services import authz
from app.services.WhatsappUsageNotifier import WhatsappUsageNotifier
from app.services.WhatsappUsageService import WhatsappUsageService
from app.utils.ResponseUtils import error_json_response, get_successful_response

logger = logging.getLogger(__name__)

whatsappUsageRouter = APIRouter(prefix="/whatsapp/usage", tags=["WhatsApp Usage"])

usage_service = WhatsappUsageService()
notifier = WhatsappUsageNotifier()


def _iso(value: Optional[datetime]) -> Optional[str]:
    if isinstance(value, datetime):
        # Mongo returns naive UTC datetimes: emit an explicit offset.
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return str(value) if value else None


def _authorize(request: Request, group_id: str, key: str):
    """Returns (uid, grants); 403 unless the caller holds `key` in the store."""
    uid = authz.caller_uid(request)
    gid = authz.selected_group(request, override=group_id)
    grants = authz.effective_grants(uid, gid, request)
    if key not in grants:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing grant: {key}")
    return uid, gid, grants


@whatsappUsageRouter.get("", description="Store usage of the WhatsApp bot (current window)")
def get_usage(request: Request, group_id: str = Query(...)):
    try:
        uid, gid, grants = _authorize(request, group_id, g.WHATSAPP_POS_INTAKE)
        snap = usage_service.snapshot(gid, uid)
        pending = usage_repo.find_pending_credit_request(gid)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(
                {
                    "tier": {
                        "name": snap.tier_name,
                        "solicitudes_per_window": snap.limit,
                        "window_seconds": snap.window_seconds,
                    },
                    "used": snap.used,
                    "limit": snap.limit,
                    "percent": snap.percent,
                    "window_end": _iso(snap.window_end),
                    "state": snap.state,
                    "is_manager": notifier.is_manager(uid, gid),
                    "can_request": g.WHATSAPP_REQUEST_CREDITS in grants,
                    "pending_request_at": _iso((pending or {}).get("created_at")),
                }
            ),
        )
    except HTTPException as e:
        return error_json_response(e)


@whatsappUsageRouter.get("/by-seller", description="Per-seller share of the store's current window")
def get_by_seller(request: Request, group_id: str = Query(...)):
    try:
        uid, gid, _ = _authorize(request, group_id, g.WHATSAPP_VIEW_USAGE)
        snap = usage_service.snapshot(gid)
        # by_seller returns the latest window even when expired.
        rows = usage_repo.by_seller(gid) if snap.window_end is not None else []
        total = sum(r["solicitudes"] for r in rows)
        names = {}
        if rows:
            users = userRepository.find({"uid": {"$in": [r["uid"] for r in rows]}}, limit=len(rows))
            names = {u["uid"]: u.get("name") or "" for u in users}
        body = [
            {
                "uid": r["uid"],
                "name": names.get(r["uid"], ""),
                "solicitudes": r["solicitudes"],
                "tokens": r["tokens"],
                "share_percent": round(r["solicitudes"] * 100 / total) if total else 0,
            }
            for r in rows
        ]
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(body))
    except HTTPException as e:
        return error_json_response(e)


@whatsappUsageRouter.post("/credit-requests", description="Ask the Eassymo team for more WhatsApp solicitudes")
def create_credit_request(request: Request, body: CreditRequestIn, group_id: str = Query(...)):
    try:
        uid, gid, _ = _authorize(request, group_id, g.WHATSAPP_REQUEST_CREDITS)
        existing = usage_repo.find_pending_credit_request(gid)
        if existing:
            return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(_public(existing)))
        created = usage_repo.create_credit_request(gid, uid, body.note)
        try:
            store = (groupRepository.find_by_id(gid, {"name": 1}) or {}).get("name") or "Tienda"
            notifier.push_admins_credit_request(gid, store, uid)
        except Exception:
            logger.exception("whatsapp_usage credit request push failed group_id=%s", gid)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(_public(created)))
    except HTTPException as e:
        return error_json_response(e)


def _public(doc: dict) -> dict:
    return {k: _iso(v) if isinstance(v, datetime) else v for k, v in doc.items()}
