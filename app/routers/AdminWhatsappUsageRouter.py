"""Super admin API for WhatsApp bot usage limits: tiers, credits, usage, settings, audit."""

import csv
import io
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Iterator, Literal, Optional

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from app.dependencies.super_admin import require_super_admin
from app.repositories import GroupRepository as groupRepository
from app.repositories import WhatsappUsageRepository as usage_repo
from app.schemas.WhatsappUsage import GrantIn, SettingsPatch, TierIn
from app.services.WhatsappUsageNotifier import WhatsappUsageNotifier
from app.services.WhatsappUsageService import WhatsappUsageService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

logger = logging.getLogger(__name__)

adminWhatsappUsageRouter = APIRouter(
    prefix="/admin/whatsapp",
    tags=["Admin WhatsApp Usage"],
    dependencies=[Depends(require_super_admin)],
)

usage_service = WhatsappUsageService()
notifier = WhatsappUsageNotifier()

DEFAULT_RANGE_DAYS = 30
CSV_COLUMNS = [
    "created_at", "group_id", "uid", "burst_id", "tier_id", "kind", "counted", "status",
    "prompt_tokens", "completion_tokens", "model", "estimated_cost", "enforcement_mode", "usage_missing",
]


def _ok(data):
    # Mongo returns naive UTC datetimes: emit them with an explicit offset.
    content = jsonable_encoder(
        get_successful_response(data),
        custom_encoder={ObjectId: str, datetime: lambda value: _aware(value).isoformat()},
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=content)


def _err(exc, code=status.HTTP_500_INTERNAL_SERVER_ERROR):
    status_code = getattr(exc, "status_code", code)
    if status_code >= 500:
        logger.error("Admin whatsapp usage endpoint failed: %s", exc, exc_info=exc)
    detail = getattr(exc, "detail", str(exc))
    return JSONResponse(status_code=status_code, content=get_unsuccessful_response(detail))


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value) -> str:
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    return "" if value is None else str(value)


def _notify_requester(resolved: dict, status_: str, amount: Optional[int]) -> None:
    """Tell the seller who asked their request was reviewed. Never raises."""
    try:
        group_id = resolved.get("group_id")
        store = (groupRepository.find_by_id(str(group_id), {"name": 1}) or {}).get("name") or "tu tienda"
        notifier.push_requester_resolved(resolved.get("requested_by"), store, status_, amount)
    except Exception:
        logger.exception("whatsapp_usage requester push failed request=%s", resolved.get("id"))


def _grant_or_reopen(request_id: Optional[str], group_id: str, amount: int, reason: str, actor, window_start):
    """add_grant; if it fails after the request was resolved, put the request back to pending."""
    try:
        return usage_repo.add_grant(group_id, amount, reason, actor, window_start)
    except Exception:
        if request_id:
            try:
                usage_repo.reopen_credit_request(request_id, "granted")
            except Exception:
                logger.exception("whatsapp_usage could not reopen request=%s", request_id)
        raise


def _parse_dt(value: Optional[str], default: datetime, field: str) -> datetime:
    if not value:
        return default
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {field}")


def _with_count(tier: dict) -> dict:
    return {**tier, "stores_count": usage_repo.count_stores_on_tier(tier["tier_id"])}


def _need_tier(tier_id: str) -> dict:
    tier = usage_repo.get_tier(tier_id)
    if not tier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
    return tier


def _tier_slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-") or "tier"


def _free_tier_id(name: str) -> str:
    base = _tier_slug(name)
    candidate, n = base, 2
    while candidate == usage_repo.NORMAL_TIER_ID or usage_repo.get_tier(candidate):
        candidate, n = f"{base}-{n}", n + 1
    return candidate


# --- Tiers ------------------------------------------------------------------

@adminWhatsappUsageRouter.get("/tiers")
def list_tiers():
    try:
        return _ok([_with_count(t) for t in usage_repo.list_tiers()])
    except Exception as e:
        return _err(e)


@adminWhatsappUsageRouter.post("/tiers")
def create_tier(body: TierIn, user: dict = Depends(require_super_admin)):
    try:
        tier_id = _free_tier_id(body.name)
        try:
            created = usage_repo.create_tier(tier_id, body.model_dump())
        except DuplicateKeyError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tier already exists")
        usage_repo.write_audit(user.get("uid"), "tier.create", tier_id, None, created)
        return _ok(_with_count(created))
    except Exception as e:
        return _err(e)


@adminWhatsappUsageRouter.patch("/tiers/{tier_id}")
def patch_tier(tier_id: str, body: TierIn, user: dict = Depends(require_super_admin)):
    try:
        before = _need_tier(tier_id)
        if tier_id == usage_repo.NORMAL_TIER_ID and not body.active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The normal tier cannot be deactivated")
        after = usage_repo.update_tier(tier_id, body.model_dump())
        if after is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
        usage_repo.write_audit(user.get("uid"), "tier.update", tier_id, before, after)
        return _ok(_with_count(after))
    except Exception as e:
        return _err(e)


# --- Stores -----------------------------------------------------------------

class StoreTierIn(BaseModel):
    tier_id: str


@adminWhatsappUsageRouter.put("/stores/{group_id}/tier")
def assign_store_tier(group_id: str, body: StoreTierIn, user: dict = Depends(require_super_admin)):
    try:
        if not _need_tier(body.tier_id).get("active", True):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
        before = usage_repo.get_store_tier_id(group_id)
        row = usage_repo.assign_store_tier(group_id, body.tier_id, user.get("uid"))
        usage_repo.write_audit(
            user.get("uid"), "store.tier", group_id, {"tier_id": before}, {"tier_id": body.tier_id}
        )
        return _ok(row)
    except Exception as e:
        return _err(e)


@adminWhatsappUsageRouter.get("/stores/{group_id}/usage")
def store_usage(group_id: str):
    try:
        snap = usage_service.snapshot(group_id)
        active = snap.window_end is not None  # by_seller returns the latest window even when expired
        rows = usage_repo.by_seller(group_id) if active else []
        return _ok(
            {
                "tier": usage_repo.get_tier(snap.tier_id),
                "used": snap.used if active else 0,
                "limit": snap.limit,
                "tokens_used": snap.tokens_used if active else 0,
                "token_ceiling": snap.token_ceiling,
                "percent": snap.percent if active else 0,
                "state": snap.state,
                "window_start": snap.window_start,
                "window_end": snap.window_end,
                "by_seller": rows,
                "grants": usage_repo.list_grants(group_id, snap.window_start if active else None),
            }
        )
    except Exception as e:
        return _err(e)


@adminWhatsappUsageRouter.post("/stores/{group_id}/credits")
def grant_credits(
    group_id: str,
    body: GrantIn,
    request_id: Optional[str] = Query(None),
    user: dict = Depends(require_super_admin),
):
    try:
        actor = user.get("uid")
        resolved = None
        if request_id:
            pending = usage_repo.get_credit_request(request_id)
            if not pending or pending.get("status") != "pending" or pending.get("group_id") != group_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending credit request not found")
            resolved = usage_repo.resolve_credit_request(request_id, "granted", actor)
            if not resolved:  # lost a race: nothing granted
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending credit request not found")
        snap = usage_service.snapshot(group_id)
        window_start = _aware(snap.window_start) if snap.window_end is not None else None
        grant = _grant_or_reopen(request_id if resolved else None, group_id, body.amount, body.reason, actor, window_start)
        usage_repo.write_audit(
            actor, "credits.grant", group_id, pending if request_id else None,
            {**grant, "request": resolved}, body.reason,
        )
        if resolved:
            _notify_requester(resolved, "granted", body.amount)
        return _ok({"grant": grant, "request": resolved})
    except Exception as e:
        return _err(e)


# --- Usage ------------------------------------------------------------------

@adminWhatsappUsageRouter.get("/usage")
def usage(since: Optional[str] = Query(None), until: Optional[str] = Query(None)):
    try:
        now = datetime.now(timezone.utc)
        end = _parse_dt(until, now, "until")
        start = _parse_dt(since, end - timedelta(days=DEFAULT_RANGE_DAYS), "since")
        data = usage_repo.aggregate_usage(start, end)
        near = usage_repo.list_active_usage(now)
        meter_errors = int(usage_repo.get_settings().get("meter_errors", 0))
        return _ok({**data, "stores_near_limit": near, "meter_errors": meter_errors})
    except Exception as e:
        return _err(e)


def _csv_rows(events: Iterator[dict]) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)

    def flush() -> str:
        value = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        return value

    writer.writerow(CSV_COLUMNS)
    yield flush()
    for event in events:
        writer.writerow([_iso(event.get(col)) if col == "created_at" else event.get(col, "") for col in CSV_COLUMNS])
        yield flush()


@adminWhatsappUsageRouter.get("/usage/export.csv")
def export_usage(since: Optional[str] = Query(None), until: Optional[str] = Query(None)):
    try:
        now = datetime.now(timezone.utc)
        end = _parse_dt(until, now, "until")
        start = _parse_dt(since, end - timedelta(days=DEFAULT_RANGE_DAYS), "since")
        return StreamingResponse(
            _csv_rows(usage_repo.iter_events(start, end)),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="whatsapp-usage.csv"'},
        )
    except Exception as e:
        return _err(e)


# --- Settings ---------------------------------------------------------------

@adminWhatsappUsageRouter.get("/settings")
def get_settings():
    try:
        return _ok(usage_repo.get_settings())
    except Exception as e:
        return _err(e)


@adminWhatsappUsageRouter.patch("/settings")
def patch_settings(body: SettingsPatch, user: dict = Depends(require_super_admin)):
    try:
        # Only SettingsPatch fields: callers can never overwrite meter_errors.
        fields = body.model_dump(exclude_unset=True, exclude_none=True)
        before = usage_repo.get_settings()
        after = usage_repo.update_settings(fields) if fields else before
        if fields:
            usage_repo.write_audit(user.get("uid"), "settings.update", "global", before, after)
        return _ok(after)
    except Exception as e:
        return _err(e)


# --- Credit requests --------------------------------------------------------

class ResolveIn(BaseModel):
    status: Literal["granted", "declined"]
    amount: Optional[int] = None
    reason: Optional[str] = None


@adminWhatsappUsageRouter.get("/credit-requests")
def list_credit_requests(status_: Optional[str] = Query(None, alias="status")):
    try:
        return _ok(usage_repo.list_credit_requests(status_))
    except Exception as e:
        return _err(e)


@adminWhatsappUsageRouter.post("/credit-requests/{request_id}/resolve")
def resolve_credit_request(request_id: str, body: ResolveIn, user: dict = Depends(require_super_admin)):
    try:
        actor = user.get("uid")
        if body.status == "granted" and (not body.amount or body.amount < 1):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="amount is required to grant")
        pending = usage_repo.get_credit_request(request_id)
        if not pending or pending.get("status") != "pending":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending credit request not found")
        resolved = usage_repo.resolve_credit_request(request_id, body.status, actor)
        if not resolved:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending credit request not found")
        grant = None
        if body.status == "granted":
            group_id = resolved["group_id"]
            snap = usage_service.snapshot(group_id)
            window_start = _aware(snap.window_start) if snap.window_end is not None else None
            grant = _grant_or_reopen(
                request_id, group_id, body.amount, body.reason or "Solicitud aprobada", actor, window_start
            )
        usage_repo.write_audit(
            actor, f"credit_request.{body.status}", resolved["group_id"], pending,
            {"request": resolved, "grant": grant}, body.reason,
        )
        _notify_requester(resolved, body.status, body.amount if body.status == "granted" else None)
        return _ok({"request": resolved, "grant": grant})
    except Exception as e:
        return _err(e)


# --- Audit ------------------------------------------------------------------

@adminWhatsappUsageRouter.get("/audit")
def audit(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    try:
        return _ok(usage_repo.list_audit(page, page_size))
    except Exception as e:
        return _err(e)
