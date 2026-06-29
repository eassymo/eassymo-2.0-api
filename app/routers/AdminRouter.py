from fastapi import APIRouter, Body, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from typing import Optional

from app.dependencies.super_admin import require_super_admin
from app.services.AdminMetricsService import AdminMetricsService
from app.services.AdminWriteService import AdminWriteService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

adminRouter = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_super_admin)],
)


def _ok(data):
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(data))


def _err(exc, code=status.HTTP_500_INTERNAL_SERVER_ERROR):
    status_code = getattr(exc, "status_code", code)
    detail = getattr(exc, "detail", str(exc))
    return JSONResponse(status_code=status_code, content=get_unsuccessful_response(detail))


# ── Metrics ─────────────────────────────────────────────────────────────────

@adminRouter.get("/overview")
def admin_overview(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.get_overview(date_from, date_to, group_id))
    except Exception as e:
        return _err(e)


@adminRouter.get("/part-requests/metrics")
def part_requests_metrics(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    granularity: str = Query("day"),
):
    try:
        return _ok(AdminMetricsService.get_part_requests_metrics(date_from, date_to, group_id, granularity))
    except Exception as e:
        return _err(e)


@adminRouter.get("/offers/metrics")
def offers_metrics(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    granularity: str = Query("day"),
):
    try:
        return _ok(AdminMetricsService.get_offers_metrics(date_from, date_to, group_id, granularity))
    except Exception as e:
        return _err(e)


@adminRouter.get("/orders/metrics")
def orders_metrics(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    granularity: str = Query("day"),
):
    try:
        return _ok(AdminMetricsService.get_orders_metrics(date_from, date_to, group_id, granularity))
    except Exception as e:
        return _err(e)


@adminRouter.get("/users/metrics")
def users_metrics(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.get_users_metrics(date_from, date_to))
    except Exception as e:
        return _err(e)


@adminRouter.get("/groups/metrics")
def groups_metrics(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.get_groups_metrics(date_from, date_to))
    except Exception as e:
        return _err(e)


@adminRouter.get("/roles/metrics")
def roles_metrics():
    try:
        return _ok(AdminMetricsService.get_roles_metrics())
    except Exception as e:
        return _err(e)


@adminRouter.get("/pending-carts/metrics")
def pending_carts_metrics():
    try:
        return _ok(AdminMetricsService.get_pending_carts_metrics())
    except Exception as e:
        return _err(e)


@adminRouter.get("/group-vehicles/metrics")
def group_vehicles_metrics():
    try:
        return _ok(AdminMetricsService.get_group_vehicles_metrics())
    except Exception as e:
        return _err(e)


@adminRouter.get("/catalogs/metrics")
def catalogs_metrics():
    try:
        return _ok(AdminMetricsService.get_catalogs_metrics())
    except Exception as e:
        return _err(e)


# ── Paginated lists ─────────────────────────────────────────────────────────

@adminRouter.get("/part-requests")
def list_part_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_part_requests(page, page_size, status, group_id, search))
    except Exception as e:
        return _err(e)


@adminRouter.get("/offers")
def list_offers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_offers(page, page_size, status, group_id))
    except Exception as e:
        return _err(e)


@adminRouter.get("/orders")
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_orders(page, page_size, status, group_id))
    except Exception as e:
        return _err(e)


@adminRouter.get("/users")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_users(page, page_size, search))
    except Exception as e:
        return _err(e)


@adminRouter.get("/groups")
def list_groups(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    group_type: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_groups(page, page_size, group_type, search))
    except Exception as e:
        return _err(e)


@adminRouter.get("/roles")
def list_roles():
    try:
        return _ok(AdminMetricsService.list_roles_catalog())
    except Exception as e:
        return _err(e)


@adminRouter.get("/user-roles")
def list_user_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_uid: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_user_roles(page, page_size, user_uid, group_id, role, active))
    except Exception as e:
        return _err(e)


@adminRouter.get("/pending-carts")
def list_pending_carts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    group_id: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_pending_carts(page, page_size, group_id))
    except Exception as e:
        return _err(e)


@adminRouter.get("/guarantees")
def list_guarantees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_guarantees(page, page_size, search))
    except Exception as e:
        return _err(e)


@adminRouter.get("/brands")
def list_brands(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_brands(page, page_size, search))
    except Exception as e:
        return _err(e)


@adminRouter.get("/group-vehicles")
def list_group_vehicles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    group_id: Optional[str] = Query(None),
    maker: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
):
    try:
        return _ok(AdminMetricsService.list_group_vehicles(page, page_size, group_id, maker, active))
    except Exception as e:
        return _err(e)


# ── Phase 2 write controls ──────────────────────────────────────────────────

@adminRouter.post("/orders/{order_id}/force-status")
def force_order_status(request: Request, order_id: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.force_order_status(
            admin_uid=admin_uid,
            order_id=order_id,
            new_status=data.get("new_status"),
            reason=data.get("reason"),
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.post("/offers/{offer_id}/force-status")
def force_offer_status(request: Request, offer_id: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.force_offer_status(
            admin_uid=admin_uid,
            offer_id=offer_id,
            new_status=data.get("new_status"),
            reason=data.get("reason"),
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.put("/part-requests/{request_id}")
def update_part_request(request: Request, request_id: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.update_part_request(admin_uid, request_id, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.post("/users/{uid}/disable")
def disable_user(request: Request, uid: str, data: dict = Body(default={})):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.disable_user(admin_uid, uid, data.get("reason"))
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.post("/users/{uid}/enable")
def enable_user(request: Request, uid: str, data: dict = Body(default={})):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.enable_user(admin_uid, uid, data.get("reason"))
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.post("/users/{uid}/roles")
def manage_user_global_role(request: Request, uid: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.manage_global_role(
            admin_uid=admin_uid,
            uid=uid,
            role=data.get("role"),
            action=data.get("action", "add"),
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.post("/user-roles")
def assign_user_role(request: Request, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.assign_user_role(admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.post("/user-roles/{assignment_id}/activate")
def activate_user_role(request: Request, assignment_id: str, data: dict = Body(default={})):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.set_user_role_active(
            admin_uid, assignment_id, data.get("active", True)
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.put("/user-roles/{assignment_id}")
def update_user_role(request: Request, assignment_id: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.update_user_role(admin_uid, assignment_id, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.delete("/user-roles/{assignment_id}")
def delete_user_role(request: Request, assignment_id: str):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.delete_user_role(admin_uid, assignment_id)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.post("/users/{uid}/super-admin")
def manage_super_admin_claim(request: Request, uid: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.manage_super_admin_claim(
            admin_uid=admin_uid,
            target_uid=uid,
            grant=data.get("grant", False),
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.delete("/pending-carts/{user_uid}")
def delete_pending_cart(request: Request, user_uid: str, group_id: str = Query(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.delete_pending_cart(admin_uid, user_uid, group_id)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.post("/brands")
def create_brand(request: Request, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.create_brand(admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.put("/brands/{brand_id}")
def update_brand(request: Request, brand_id: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.update_brand(admin_uid, brand_id, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.delete("/brands/{brand_id}")
def delete_brand(request: Request, brand_id: str):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.delete_brand(admin_uid, brand_id)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.post("/guarantees")
def create_guarantee(request: Request, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.create_guarantee(admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.put("/guarantees/{guarantee_id}")
def update_guarantee(request: Request, guarantee_id: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.update_guarantee(admin_uid, guarantee_id, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.delete("/guarantees/{guarantee_id}")
def delete_guarantee(request: Request, guarantee_id: str):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.delete_guarantee(admin_uid, guarantee_id)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.put("/group-vehicles/{vehicle_id}")
def update_group_vehicle(request: Request, vehicle_id: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.update_group_vehicle(admin_uid, vehicle_id, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.put("/groups/{group_id}")
def update_group(request: Request, group_id: str, data: dict = Body(...)):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.update_group(admin_uid, group_id, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.get("/audit-log")
def list_audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    try:
        return _ok(AdminWriteService.list_audit_log(page, page_size))
    except Exception as e:
        return _err(e)
