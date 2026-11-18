from fastapi import APIRouter, Body, Depends, File, Query, Request, UploadFile, status
from bson import ObjectId
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.config.database import get_mysql_db
from app.dependencies.super_admin import require_super_admin
from app.services import AccessAdminService
from app.services import FrameAdminService
from app.services.AdminMetricsService import AdminMetricsService
from app.services.AdminPartCatalogService import AdminPartCatalogService
from app.services.AdminWriteService import AdminWriteService
from app.services.AdminWhatsappInboundService import AdminWhatsappInboundService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

adminRouter = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_super_admin)],
)


def _ok(data):
    # Services return raw Mongo documents: make dates and ObjectIds JSON-safe for every admin endpoint.
    content = jsonable_encoder(get_successful_response(data), custom_encoder={ObjectId: str})
    return JSONResponse(status_code=status.HTTP_200_OK, content=content)


logger = logging.getLogger(__name__)


def _err(exc, code=status.HTTP_500_INTERNAL_SERVER_ERROR):
    status_code = getattr(exc, "status_code", code)
    if status_code >= 500:
        logger.error("Admin endpoint failed: %s", exc, exc_info=exc)
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


@adminRouter.get("/whatsapp-inbound")
def list_whatsapp_inbound(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    from_number: Optional[str] = Query(None),
    extraction_status: Optional[str] = Query(None),
    processing_status: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
):
    try:
        return _ok(
            AdminWhatsappInboundService.list_messages(
                page,
                page_size,
                from_number=from_number,
                extraction_status=extraction_status,
                processing_status=processing_status,
                group_id=group_id,
            )
        )
    except Exception as e:
        return _err(e)


@adminRouter.get("/whatsapp-inbound/{message_id}")
def get_whatsapp_inbound(message_id: str):
    try:
        return _ok(AdminWhatsappInboundService.get_message(message_id))
    except Exception as e:
        return _err(e)


# ── Part catalog (MySQL) ────────────────────────────────────────────────────

@adminRouter.get("/part-catalog/parts")
def list_part_catalog_parts(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        return _ok(AdminPartCatalogService.list_part_types(mysql_db, page, page_size))
    except Exception as e:
        return _err(e)


@adminRouter.get("/part-catalog/tags")
def list_part_catalog_tags(
    categoriaId: int = Query(...),
    subCategoriaId: int = Query(...),
    tipoParteId: int = Query(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        return _ok(
            AdminPartCatalogService.list_part_tags(
                mysql_db, categoriaId, subCategoriaId, tipoParteId
            )
        )
    except Exception as e:
        return _err(e)


@adminRouter.post("/part-catalog/tags")
def create_part_catalog_tag(
    request: Request,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.create_part_synonym(mysql_db, admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.put("/part-catalog/tags/{tipo_parte_tag_id}")
def update_part_catalog_tag(
    request: Request,
    tipo_parte_tag_id: int,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.update_part_synonym(
            mysql_db, admin_uid, tipo_parte_tag_id, data
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.delete("/part-catalog/tags/{tipo_parte_tag_id}")
def delete_part_catalog_tag(
    request: Request,
    tipo_parte_tag_id: int,
    categoriaId: int = Query(...),
    subCategoriaId: int = Query(...),
    tipoParteId: int = Query(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.delete_part_synonym(
            mysql_db,
            admin_uid,
            tipo_parte_tag_id,
            {
                "categoriaId": categoriaId,
                "subCategoriaId": subCategoriaId,
                "tipoParteId": tipoParteId,
            },
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.get("/measurement-units")
def list_measurement_units(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        return _ok(
            AdminPartCatalogService.list_measurement_units(
                mysql_db, page, page_size, search
            )
        )
    except Exception as e:
        return _err(e)


@adminRouter.post("/measurement-units")
def create_measurement_unit(
    request: Request,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.create_measurement_unit(mysql_db, admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.put("/measurement-units/{unit_id}")
def update_measurement_unit(
    request: Request,
    unit_id: int,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.update_measurement_unit(
            mysql_db, admin_uid, unit_id, data
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.delete("/measurement-units/{unit_id}")
def delete_measurement_unit(
    request: Request,
    unit_id: int,
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.delete_measurement_unit(mysql_db, admin_uid, unit_id)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.get("/part-catalog/units")
def list_part_catalog_units(
    categoriaId: int = Query(...),
    subCategoriaId: int = Query(...),
    tipoParteId: int = Query(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        return _ok(
            AdminPartCatalogService.list_part_unit_links(
                mysql_db, categoriaId, subCategoriaId, tipoParteId
            )
        )
    except Exception as e:
        return _err(e)


@adminRouter.post("/part-catalog/units/link")
def link_part_catalog_unit(
    request: Request,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.link_part_unit(mysql_db, admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.delete("/part-catalog/units/link")
def unlink_part_catalog_unit(
    request: Request,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.unlink_part_unit(mysql_db, admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.get("/positions")
def list_positions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        return _ok(
            AdminPartCatalogService.list_positions(mysql_db, page, page_size, search)
        )
    except Exception as e:
        return _err(e)


@adminRouter.post("/positions")
def create_position(
    request: Request,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.create_position(mysql_db, admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.put("/positions/{position_id}")
def update_position(
    request: Request,
    position_id: int,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.update_position(
            mysql_db, admin_uid, position_id, data
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.delete("/positions/{position_id}")
def delete_position(
    request: Request,
    position_id: int,
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.delete_position(mysql_db, admin_uid, position_id)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.get("/part-catalog/positions")
def list_part_catalog_positions(
    categoriaId: int = Query(...),
    subCategoriaId: int = Query(...),
    tipoParteId: int = Query(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        return _ok(
            AdminPartCatalogService.list_part_position_links(
                mysql_db, categoriaId, subCategoriaId, tipoParteId
            )
        )
    except Exception as e:
        return _err(e)


@adminRouter.post("/part-catalog/positions/link")
def link_part_catalog_position(
    request: Request,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.link_part_position(mysql_db, admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


@adminRouter.delete("/part-catalog/positions/link")
def unlink_part_catalog_position(
    request: Request,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        admin_uid = request.state.user.get("uid")
        result = AdminWriteService.unlink_part_position(mysql_db, admin_uid, data)
        return _ok(result)
    except Exception as e:
        return _err(e)


# ── Accesos (grants & roles) ────────────────────────────────────────────────

def _admin_uid(request: Request) -> str:
    return request.state.user.get("uid")


@adminRouter.get("/grants")
def access_list_grants():
    try:
        return _ok(AccessAdminService.list_grants())
    except Exception as e:
        return _err(e)


@adminRouter.put("/grants/{key}")
def access_update_grant(request: Request, key: str, data: dict = Body(...)):
    try:
        return _ok(AccessAdminService.update_grant(_admin_uid(request), key, data))
    except Exception as e:
        return _err(e)


@adminRouter.get("/grants/{key}/impact")
def access_grant_impact(key: str):
    try:
        return _ok(AccessAdminService.grant_impact(key))
    except Exception as e:
        return _err(e)


@adminRouter.get("/access-roles")
def access_list_roles(
    pov: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    function: Optional[str] = Query(None),
    kind: Optional[str] = Query(None, description="system | custom"),
):
    try:
        return _ok(AccessAdminService.list_roles(
            {"pov": pov, "entity_type": entity_type, "function": function, "kind": kind}))
    except Exception as e:
        return _err(e)


@adminRouter.post("/access-roles")
def access_create_role(request: Request, data: dict = Body(...)):
    try:
        return _ok(AccessAdminService.create_role(_admin_uid(request), data))
    except Exception as e:
        return _err(e)


@adminRouter.put("/access-roles/{value}")
def access_update_role(request: Request, value: str, data: dict = Body(...)):
    try:
        return _ok(AccessAdminService.update_role(_admin_uid(request), value, data))
    except Exception as e:
        return _err(e)


@adminRouter.delete("/access-roles/{value}")
def access_delete_role(request: Request, value: str):
    try:
        return _ok(AccessAdminService.delete_role(_admin_uid(request), value))
    except Exception as e:
        return _err(e)


@adminRouter.post("/access-roles/{value}/duplicate")
def access_duplicate_role(request: Request, value: str):
    try:
        return _ok(AccessAdminService.duplicate_role(_admin_uid(request), value))
    except Exception as e:
        return _err(e)


@adminRouter.get("/access-roles/{value}/impact")
def access_role_impact(value: str):
    try:
        return _ok(AccessAdminService.role_impact(value))
    except Exception as e:
        return _err(e)


@adminRouter.get("/access-check")
def access_check(uid: str = Query(...), group_id: str = Query(...)):
    try:
        return _ok(AccessAdminService.access_check(uid, group_id))
    except Exception as e:
        return _err(e)


@adminRouter.get("/access/metrics")
def access_metrics():
    try:
        return _ok(AccessAdminService.metrics())
    except Exception as e:
        return _err(e)


# ── Accesos: frames ─────────────────────────────────────────────────────────

@adminRouter.get("/frames")
def access_list_frames():
    try:
        return _ok(FrameAdminService.list_frames())
    except Exception as e:
        return _err(e)


@adminRouter.put("/frames/{code}")
def access_update_frame(request: Request, code: str, data: dict = Body(...)):
    try:
        return _ok(FrameAdminService.update_frame(_admin_uid(request), code, data))
    except Exception as e:
        return _err(e)


@adminRouter.post("/frames/{code}/screenshot")
async def access_upload_frame_screenshot(request: Request, code: str, file: UploadFile = File(...)):
    try:
        return _ok(await FrameAdminService.upload_screenshot(_admin_uid(request), code, file))
    except Exception as e:
        return _err(e)
