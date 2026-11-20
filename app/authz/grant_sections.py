"""Where each grant is enforced today.

A grant only does something where code checks it. This registry lists, per grant, the API
endpoints that check it and the app sections the client gates with it. It drives the
"Sin efecto" flag in super-admin → Accesos → Permisos, and tests/test_grant_links.py
proves every API entry (with and without the grant). The client proves its entries in
src/common/auth/grant-sections.test.tsx (GRANT_SECTIONS).

Add an entry in the same change that adds a check, together with its test.
"""
from typing import Dict, List, TypedDict

from app.authz import grant_keys as g


class Section(TypedDict):
    layer: str  # "api" | "app"
    section: str


def _api(section: str) -> Section:
    return {"layer": "api", "section": section}


def _app(section: str) -> Section:
    return {"layer": "app", "section": section}


GRANT_SECTIONS: Dict[str, List[Section]] = {
    g.WHATSAPP_CREATE_DRAFT: [
        _api("Intake de WhatsApp: crear borradores (WhatsappIntakeVerificationService)"),
        _api("Identidad de vendedor en WhatsApp (WhatsappSellerIdentityService)"),
        _api("Migración de enlaces de WhatsApp (WhatsappLinkMigrationService)"),
    ],
    g.TEAM_INVITE: [
        _api("POST /team-member-invite"),
    ],
    g.TEAM_ASSIGN_ROLES: [
        _api("POST /userRoles, /userRoles/add-role-to-user, /userRoles/delete-role-from-user, /userRoles/activate-role"),
        _api("GET /roles?assignable=true"),
        _app("Mi equipo: agregar y quitar roles"),
    ],
    g.DELIVERIES_PERFORM: [
        _api("GET /delivery-persons (selector de repartidor)"),
        _api("POST /order/assign-delivery (repartidor del grupo)"),
        _api("GET /delivery/my-orders"),
        _api("GET /delivery/invite/{token}/eligibility"),
        _api("POST /order/change-status (repartidor: solo marcar recibido)"),
        _api("POST /delivery/report-failed (repartidor con cuenta; invitados por enlace)"),
        _api("POST /delivery/route-legs (repartidor con cuenta; invitados por enlace)"),
        _app("Menú: Mis entregas (/deliveries)"),
    ],
    g.ORDERS_CHANGE_STATUS: [
        _api("POST /order/change-status (sin este permiso un repartidor solo marca recibido)"),
    ],
    g.REQUESTS_CREATE: [_app("Menú: Crear solicitud (/configure-request)")],
    g.STORE_EDIT_PROFILE: [
        _app("Menú: Configurar tienda (/shop-creator-v3)"),
        _app("Mi cuenta: Mi tienda (/profile/my-store)"),
    ],
    g.TEAM_VIEW: [_app("Mi cuenta: Mi equipo (/my-team)")],
    g.REPORTS_VIEW: [_app("Mi cuenta: Transacciones (/user-configuration/transactions)")],
    g.RELATIONSHIPS_MANAGE: [_app("Mi cuenta: Tus relaciones (/relaciones)")],
    g.NETWORK_VIEW: [_app("Mi cuenta: Mi red (/profile/my-lists)")],
    g.WHATSAPP_POS_INTAKE: [_app("Mi cuenta: WhatsApp para POS (/user-configuration/whatsapp-pos)")],
    g.WHATSAPP_VIEW_USAGE: [_api("GET /whatsapp/usage/by-seller")],
    g.WHATSAPP_REQUEST_CREDITS: [_api("POST /whatsapp/usage/credit-requests")],
    g.ORDERS_VIEW: [_app("Menú: Mis pedidos / ventas (/order-management-v2)")],
    g.REQUESTS_VIEW: [_app("Panel principal (/dashboard-v2) para quien también entrega")],
    g.OFFERS_VIEW_INCOMING: [_app("Panel principal (/dashboard-v2) para quien también entrega")],
}


def api_keys() -> set:
    return {k for k, sections in GRANT_SECTIONS.items() if any(s["layer"] == "api" for s in sections)}
