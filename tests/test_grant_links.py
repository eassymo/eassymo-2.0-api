"""Every grant must control exactly the API sections registered for it in
app/authz/grant_sections.py: allowed with the grant, denied without it.

Each test drives the real endpoint/service code; only storage and the caller's grants are
faked. `test_every_api_grant_has_a_link_test` fails when a check is added to the registry
without a test here.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.authz import grant_keys as g
from app.authz.grant_sections import GRANT_SECTIONS, api_keys
from app.services import authz

GID = str(ObjectId())
# Grants whose API links are proven below; must equal the API entries of the registry.
TESTED_API_KEYS = {
    g.WHATSAPP_CREATE_DRAFT,
    g.TEAM_INVITE,
    g.TEAM_ASSIGN_ROLES,
    g.DELIVERIES_PERFORM,
    g.ORDERS_CHANGE_STATUS,
}


def _request(uid="caller", group=GID):
    req = MagicMock()
    req.state = SimpleNamespace(user={"uid": uid}, groupSelected=group)
    req.headers = {}
    return req


def _grants(*keys):
    return patch.object(authz, "effective_grants", return_value=frozenset(keys))


# ── registry ────────────────────────────────────────────────────────────────

def test_registry_keys_exist_in_catalog():
    assert set(GRANT_SECTIONS) <= set(g.ALL_KEYS)
    for sections in GRANT_SECTIONS.values():
        assert sections and all(s["layer"] in ("api", "app") and s["section"] for s in sections)


def test_app_registry_matches_client_grant_sections():
    # Mirrors GRANT_SECTIONS in eassymo-2.0-client src/common/auth/grant-capabilities.ts,
    # whose links are proven by grant-sections.test.tsx.
    app_keys = {k for k, ss in GRANT_SECTIONS.items() if any(s["layer"] == "app" for s in ss)}
    assert app_keys == {
        g.REQUESTS_CREATE, g.STORE_EDIT_PROFILE, g.ORDERS_VIEW, g.DELIVERIES_PERFORM,
        g.REQUESTS_VIEW, g.OFFERS_VIEW_INCOMING, g.TEAM_ASSIGN_ROLES,
    }


# ── whatsapp.create_draft ───────────────────────────────────────────────────

KEY = g.WHATSAPP_CREATE_DRAFT


@pytest.mark.parametrize("granted,allowed", [(True, True), (False, False)])
def test_whatsapp_intake_requires_create_draft(granted, allowed):
    from app.services import WhatsappIntakeVerificationService as mod

    with _grants(*([KEY] if granted else [])), \
         patch.object(mod.group_auth, "user_belongs_to_group", return_value=True), \
         patch.object(mod.link_repo, "find", return_value=None):
        if allowed:
            mod.WhatsappIntakeVerificationService._assert_can_use("u", GID)
        else:
            with pytest.raises(HTTPException) as exc:
                mod.WhatsappIntakeVerificationService._assert_can_use("u", GID)
            assert exc.value.status_code == 403


@pytest.mark.parametrize("granted", [True, False])
def test_whatsapp_seller_identity_requires_create_draft(granted):
    from app.services.WhatsappSellerIdentityService import WhatsappSellerIdentityService

    with _grants(*([KEY] if granted else [])):
        assert WhatsappSellerIdentityService._link_allowed({"status": "active", "uid": "u", "group_id": GID}) is granted


def test_whatsapp_link_migration_checks_create_draft():
    from app.services import WhatsappLinkMigrationService as mod

    assert mod.PERMISSION_WHATSAPP_CREATE_DRAFT == KEY
    assert mod.can is authz.can


# ── team.invite ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("granted,status", [(True, 200), (False, 403)])
def test_team_invite_requires_team_invite(granted, status):
    from app.routers import TeamMemberInviteRouter as router
    from app.schemas.TeamMemberInvite import TeamMemberInvite

    invite = TeamMemberInvite(group=GID, role=str(ObjectId()), contact_method="+520000000000")
    role = {"value": "213", "grants": [g.OFFERS_CREATE], "assignable_by_group_admins": True}
    with _grants(*([g.OFFERS_CREATE] + ([g.TEAM_INVITE] if granted else []))), \
         patch.object(authz, "resolve_role_value", return_value="213"), \
         patch.object(authz.RolesRepository, "find_by_value", return_value=role), \
         patch.object(authz.groupRepository, "find_by_id", return_value={"_id": GID, "type": 1}), \
         patch.object(authz.group_auth, "is_group_owner", return_value=False), \
         patch.object(router.teamMemberInviteService, "insert", return_value={"invite_id": "x"}):
        resp = router.insert(_request(), invite)
    assert resp.status_code == status


# ── team.assign_roles ───────────────────────────────────────────────────────

ROLE = {"value": "r_cajero", "grants": [g.OFFERS_CREATE], "assignable_by_group_admins": True, "entity_types": ["1"]}


@pytest.fixture
def assignable_role():
    with patch.object(authz.RolesRepository, "find_by_value", return_value=ROLE), \
         patch.object(authz.groupRepository, "find_by_id", return_value={"_id": GID, "type": 1}), \
         patch.object(authz.group_auth, "is_group_owner", return_value=False), \
         patch("app.dependencies.group_auth.is_group_owner", return_value=False):
        yield


@pytest.mark.parametrize("granted,status", [(True, 200), (False, 403)])
def test_add_role_to_user_requires_assign_roles(assignable_role, granted, status):
    from app.routers import UserRolesRouter as router

    grants = [g.OFFERS_CREATE] + ([g.TEAM_ASSIGN_ROLES] if granted else [])
    with _grants(*grants), patch.object(router.userRolesService, "add_role_to_user", return_value={"ok": True}):
        resp = router.add_role_to_user(_request(), {"user_uid": "member", "role": "r_cajero", "group": GID})
    assert resp.status_code == status


@pytest.mark.parametrize("granted,status", [(True, 200), (False, 403)])
def test_remove_role_requires_assign_roles_for_non_owner(assignable_role, granted, status):
    from app.routers import UserRolesRouter as router

    grants = [g.OFFERS_CREATE] + ([g.TEAM_ASSIGN_ROLES] if granted else [])
    with _grants(*grants), patch.object(router.userRolesService, "remove_role_from_user", return_value={"ok": True}):
        resp = router.remove(_request(), {"user_uid": "member", "role": "r_cajero", "group": GID})
    assert resp.status_code == status


@pytest.mark.parametrize("granted,expected", [(True, ["r_cajero"]), (False, [])])
def test_assignable_roles_list_requires_assign_roles(assignable_role, granted, expected):
    from app.routers import RolesRouter as router

    grants = [g.OFFERS_CREATE] + ([g.TEAM_ASSIGN_ROLES] if granted else [])
    # team.invite is absent, so only team.assign_roles can put the role in the list
    with _grants(*grants), patch.object(router.rolesRepository, "find", return_value=[{**ROLE, "_id": ObjectId()}]):
        resp = router.find(_request(), assignable=True, all=False)
    assert [r["value"] for r in json.loads(resp.body)] == expected


# ── deliveries.perform ──────────────────────────────────────────────────────

DRIVER_ROLE = {"value": "tpl.v.repartidor", "grants": [g.DELIVERIES_PERFORM]}
OTHER_ROLE = {"value": "tpl.v.vendedor", "grants": [g.OFFERS_CREATE]}


def _roles_with(granted):
    return patch.object(authz.RolesRepository, "find", return_value=[DRIVER_ROLE if granted else OTHER_ROLE])


def _user_roles_matching(value):
    """UserRoles.find stub: rows only when the queried role list contains `value`."""
    def find(query):
        roles = (query.get("role") or {}).get("$in", [])
        return [SimpleNamespace(user_uid="driver", role=value)] if value in roles else []
    return find


@pytest.mark.parametrize("granted", [True, False])
def test_delivery_persons_list_follows_deliveries_perform(granted):
    from app.services import DeliveryService as svc

    with _roles_with(granted), \
         patch.object(svc, "_assert_user_in_group"), \
         patch.object(svc.userRolesRepository, "find", side_effect=_user_roles_matching("tpl.v.repartidor")), \
         patch.object(svc.userRepository, "find", return_value=[{"uid": "driver", "name": "Luis"}]):
        result = svc.get_delivery_persons(GID, "caller")
    assert [u["uid"] for u in result] == (["driver"] if granted else [])


@pytest.mark.parametrize("granted", [True, False])
def test_assign_delivery_follows_deliveries_perform(granted):
    from app.services import DeliveryService as svc

    with _roles_with(granted), \
         patch.object(svc.userRolesRepository, "find", side_effect=_user_roles_matching("tpl.v.repartidor")):
        if granted:
            assert svc.build_delivery_assignment("group_member", "driver", None, None, GID).user_id == "driver"
        else:
            with pytest.raises(HTTPException) as exc:
                svc.build_delivery_assignment("group_member", "driver", None, None, GID)
            assert exc.value.status_code == 404


@pytest.mark.parametrize("granted", [True, False])
def test_my_deliveries_follow_deliveries_perform(granted):
    from app.services import DeliveryService as svc

    with _roles_with(granted), \
         patch.object(svc.userRolesRepository, "find", side_effect=_user_roles_matching("tpl.v.repartidor")), \
         patch.object(svc, "_fetch_orders_for_delivery", return_value=[]):
        if granted:
            assert svc.get_my_orders("driver", None) == []
        else:
            with pytest.raises(HTTPException) as exc:
                svc.get_my_orders("driver", None)
            assert exc.value.status_code == 403


@pytest.mark.parametrize("granted", [True, False])
def test_invite_eligibility_follows_deliveries_perform(granted):
    from app.services import DeliveryService as svc

    with _roles_with(granted), \
         patch.object(svc.userRolesRepository, "find", side_effect=_user_roles_matching("tpl.v.repartidor")):
        assert svc._user_has_delivery_role_in_group("driver", GID) is granted


# ── deliveries.perform + orders.change_status on POST /order/change-status ─

@pytest.mark.parametrize("grants,restricted", [
    ({g.DELIVERIES_PERFORM}, True),
    ({g.DELIVERIES_PERFORM, g.ORDERS_CHANGE_STATUS}, False),
    ({g.ORDERS_CHANGE_STATUS}, False),
])
def test_change_status_restriction_follows_grants(grants, restricted):
    from app.routers import OrderRouter

    req = SimpleNamespace(state=SimpleNamespace(groupSelected=GID), headers={})
    with _grants(*grants):
        assert OrderRouter._is_delivery_restricted_caller(req, {"uid": "u"}) is restricted


# ── completeness ────────────────────────────────────────────────

def test_every_api_grant_has_a_link_test():
    assert TESTED_API_KEYS == api_keys()


def test_change_status_restriction_cannot_be_dodged_by_header():
    """A template repartidor omits or swaps the GroupSelected header: the order's seller group still decides."""
    from app.routers import OrderRouter

    seller = str(ObjectId())
    req = SimpleNamespace(state=SimpleNamespace(groupSelected=None), headers={})
    grants_by_group = {seller: frozenset({g.DELIVERIES_PERFORM})}
    with patch.object(OrderRouter, "_order_seller_group", return_value=seller), \
         patch.object(authz, "effective_grants", side_effect=lambda uid, gid, r=None: grants_by_group.get(gid, frozenset())):
        assert OrderRouter._is_delivery_restricted_caller(req, {"uid": "driver"}, "order-1") is True
