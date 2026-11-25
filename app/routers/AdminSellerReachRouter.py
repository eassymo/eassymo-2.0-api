"""Super admin API for the seller reach cap: global limits, per-store overrides and the audit trail."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.dependencies.super_admin import require_super_admin
from app.repositories import SellerReachRepository as repo
from app.schemas.SellerReach import ReachSettingsPatch
from app.services import authz
from app.utils.ResponseUtils import error_json_response, get_successful_response

adminSellerReachRouter = APIRouter(
    prefix="/admin/seller-reach",
    tags=["Admin Seller Reach"],
    dependencies=[Depends(require_super_admin)],
)

EVENTS_PAGE_SIZE = 50


def _ok(body):
    # Mongo returns naive UTC datetimes: emit them with an explicit offset.
    content = jsonable_encoder(
        get_successful_response(body),
        custom_encoder={datetime: lambda v: (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()},
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=content)


def _validate(incoming: dict, base: dict) -> None:
    """Field bounds on what was sent, then threshold > capped_max on the merged result."""
    problems = []
    if incoming.get("wide_per_day") is not None and incoming["wide_per_day"] < 0:
        problems.append("wide_per_day debe ser 0 o más")
    if incoming.get("capped_max") is not None and incoming["capped_max"] < 1:
        problems.append("capped_max debe ser 1 o más")
    merged = {**base, **incoming}
    if merged["wide_threshold"] <= merged["capped_max"]:
        problems.append("wide_threshold debe ser mayor que capped_max")
    if problems:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(problems))


def _fields(patch: ReachSettingsPatch) -> dict:
    return patch.model_dump(exclude_none=True)


@adminSellerReachRouter.get("/settings", description="Global seller reach limits")
def get_settings():
    try:
        return _ok(repo.get_settings())
    except HTTPException as e:
        return error_json_response(e)


@adminSellerReachRouter.put("/settings", description="Change the global seller reach limits")
def put_settings(request: Request, patch: ReachSettingsPatch):
    try:
        fields = _fields(patch)
        _validate(fields, repo.get_settings())
        return _ok(repo.update_settings(fields, authz.caller_uid(request)))
    except HTTPException as e:
        return error_json_response(e)


@adminSellerReachRouter.get("/stores", description="Stores with their own limits")
def list_stores():
    try:
        return _ok({"items": repo.list_overrides()})
    except HTTPException as e:
        return error_json_response(e)


@adminSellerReachRouter.put("/stores/{group_id}", description="Override the limits for one store")
def put_store(request: Request, group_id: str, patch: ReachSettingsPatch):
    try:
        fields = _fields(patch)
        base = {**repo.get_settings(), **{k: v for k, v in (repo.get_override(group_id) or {}).items() if v is not None}}
        _validate(fields, base)
        return _ok(repo.set_override(group_id, fields, authz.caller_uid(request)))
    except HTTPException as e:
        return error_json_response(e)


@adminSellerReachRouter.delete("/stores/{group_id}", description="Remove a store's override")
def delete_store(request: Request, group_id: str):
    try:
        repo.clear_override(group_id, authz.caller_uid(request))
        return _ok({"group_id": group_id})
    except HTTPException as e:
        return error_json_response(e)


@adminSellerReachRouter.get("/events", description="Seller reach audit events, newest first")
def get_events(page: int = Query(1, ge=1), group_id: Optional[str] = Query(None)):
    try:
        return _ok(repo.list_events(page, EVENTS_PAGE_SIZE, group_id))
    except HTTPException as e:
        return error_json_response(e)
