from typing import Optional

from fastapi import APIRouter, Query, Request

from app.dependencies import group_auth
from app.services import authz

meRouter = APIRouter(prefix="/me", tags=["Me"])


@meRouter.get("/grants", description="Effective grants of the caller in a group (default: GroupSelected header)")
def my_grants(request: Request, group_id: Optional[str] = Query(None)):
    uid = authz.caller_uid(request)
    gid = authz.selected_group(request, override=group_id)
    grants = authz.effective_grants(uid, gid, request)
    is_owner = group_auth.user_belongs_to_group(uid, gid) and group_auth.is_group_owner(uid, gid)
    return {"body": {"group_id": gid, "is_owner": bool(is_owner), "grants": sorted(grants)}}
