from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import DeliveryService as svc
from app.services import authz

ROLE_DOCS = [
    {"value": "215", "grants": ["deliveries.perform", "chat.private"]},
    {"value": "212", "grants": ["offers.create"]},
    {"value": "tpl.v.repartidor", "grants": ["deliveries.perform", "orders.view"]},
    {"value": "old", "grants": ["deliveries.perform"], "active": False},
]


def test_delivery_role_values_are_roles_granting_deliveries():
    with patch.object(authz.RolesRepository, "find", return_value=ROLE_DOCS) as find:
        assert authz.delivery_role_values() == ["215", "tpl.v.repartidor"]
    assert {"grants": "deliveries.perform"} in find.call_args[0][0]["$or"]


def test_unmigrated_215_still_counts_as_delivery_role():
    with patch.object(authz.RolesRepository, "find", return_value=[{"value": 215}, {"value": 212}]):
        assert authz.delivery_role_values() == ["215"]


@patch.object(svc, "_assert_user_in_group")
@patch.object(svc.userRepository, "find", return_value=[{"uid": "d1", "name": "Ana"}])
@patch.object(svc.userRolesRepository, "find", return_value=[SimpleNamespace(user_uid="d1")])
@patch.object(svc.authz, "delivery_role_variants", return_value=["215", "tpl.v.repartidor"])
def test_delivery_persons_query_uses_grant_roles(_vals, roles_find, _users, _assert):
    result = svc.get_delivery_persons("g1", "caller")
    assert roles_find.call_args[0][0] == {
        "role": {"$in": ["215", "tpl.v.repartidor"]}, "group": "g1", "active": True}
    assert [u["uid"] for u in result] == ["d1"]


@patch.object(svc.userRolesRepository, "find", return_value=[])
@patch.object(svc.authz, "delivery_role_variants", return_value=["215"])
def test_assign_rejects_member_without_delivery_grant(_vals, _find):
    with pytest.raises(HTTPException) as exc:
        svc.build_delivery_assignment("group_member", "u212", None, None, "g1")
    assert exc.value.status_code == 404


@patch.object(svc.userRolesRepository, "find", return_value=[])
@patch.object(svc.authz, "delivery_role_variants", return_value=["215"])
def test_my_orders_requires_delivery_grant(_vals, _find):
    with pytest.raises(HTTPException) as exc:
        svc.get_my_orders("u", None)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("grants,expected", [
    ({"deliveries.perform", "chat.private"}, True),
    ({"deliveries.perform", "orders.change_status"}, False),
    ({"offers.create", "orders.change_status"}, False),
    (set(), False),
])
def test_is_delivery_restricted(grants, expected):
    assert authz.is_delivery_restricted(frozenset(grants)) is expected


from app.routers import OrderRouter


def _req(group="g1"):  # order lookups are stubbed in the tests below
    return SimpleNamespace(state=SimpleNamespace(groupSelected=group), headers={})


def test_order_router_restricts_delivery_only_caller():
    with patch.object(OrderRouter.authz, "effective_grants", return_value=frozenset({"deliveries.perform"})):
        assert OrderRouter._is_delivery_restricted_caller(_req(), {"uid": "u"}) is True


def test_order_router_does_not_restrict_seller_admin():
    with patch.object(OrderRouter.authz, "effective_grants",
                      return_value=frozenset({"deliveries.perform", "orders.change_status"})):
        assert OrderRouter._is_delivery_restricted_caller(_req(), {"uid": "u"}) is False


def test_order_router_keeps_legacy_claim_without_group():
    assert OrderRouter._is_delivery_restricted_caller(_req(group=None), {"uid": "u", "roles": ["215"]}) is True
    assert OrderRouter._is_delivery_restricted_caller(_req(group=None), {"uid": "u"}) is False


def test_value_variants_cover_numeric_legacy_values():
    from app.repositories import RolesRepository
    assert RolesRepository.value_variants(["215", "tpl.v.admin", 212]) == ["215", 215, "tpl.v.admin", "212", 212]


def test_all_grants_role_counts_as_delivery_role():
    docs = [{"value": "super_admin", "all_grants": True, "grants": []}, {"value": 212, "grants": ["offers.create"]}]
    with patch.object(authz.RolesRepository, "find", return_value=docs) as find:
        assert authz.delivery_role_values() == ["super_admin"]
    assert {"all_grants": True} in find.call_args[0][0]["$or"]


@patch.object(svc.userRolesRepository, "find", return_value=[])
@patch.object(svc.authz, "delivery_role_variants", return_value=["215"])
def test_group_owner_can_open_my_deliveries(_vals, _find):
    """Owners hold deliveries.perform (the app shows them 'Mis entregas'); the API must agree."""
    with patch.object(svc.groupRepository, "find", return_value=[{"_id": "g1"}]), \
         patch.object(svc, "_fetch_orders_for_delivery", return_value=[]):
        assert svc.get_my_orders("owner-uid", None) == []


# ── new delivery endpoints (report-failed, route-legs, guest feed) ──────────

import main
from tests.asgi_client import AsgiClient

ORDER_ID = "6560f0aa0000000000000001"


async def _account(request):
    request.state.user = {"uid": "no-grant-uid"}
    request.state.groupSelected = "g1"
    return request.state.user


@pytest.fixture
def account_client():
    with patch.object(main, "verify_token", side_effect=_account):
        yield AsgiClient(main.app)


@pytest.mark.parametrize("path,body", [
    ("/delivery/report-failed", {"order_id": ORDER_ID, "reason": "no_answer"}),
    ("/delivery/route-legs", {"origin": {"lat": 19.4, "lng": -99.1}, "stops": [{"lat": 19.3, "lng": -99.2}]}),
])
def test_account_without_deliveries_perform_is_403(account_client, path, body):
    with patch.object(svc.userRolesRepository, "find", return_value=[]), \
         patch.object(svc.authz, "delivery_role_variants", return_value=["215"]), \
         patch.object(svc.groupRepository, "find", return_value=[]), \
         patch.object(svc.orderRepository, "find_one", side_effect=AssertionError("no order read before the grant")), \
         patch("app.services.RouteService.get_route_legs", side_effect=AssertionError("no Directions call")):
        res = account_client.post(path, json=body)
    assert res.status_code == 403


GUEST_CALLS = [
    ("GET", "/delivery/guest-notifications", None),
    ("POST", "/delivery/guest-notifications/read", {}),
    ("POST", "/delivery/report-failed", {"order_id": ORDER_ID, "reason": "no_answer"}),
    ("POST", "/delivery/route-legs", {"origin": {"lat": 19.4, "lng": -99.1}, "stops": [{"lat": 19.3, "lng": -99.2}]}),
]


async def _no_firebase(_request):
    raise HTTPException(status_code=401, detail="Missing or invalid token")


@pytest.mark.parametrize("method,path,body", GUEST_CALLS)
def test_all_guest_endpoints_return_guest_token_inactive_for_a_deactivated_profile(method, path, body):
    profile = {"token": "tok-off", "name": "Beto", "status": "inactive"}
    with patch.object(main, "verify_token", side_effect=_no_firebase), \
         patch.object(svc.guestProfileRepository, "find_by_token", return_value=profile), \
         patch.object(svc, "_ensure_guest_profile") as reactivate:
        res = AsgiClient(main.app).request(method, path, headers={"X-Guest-Token": "tok-off"}, json=body)
    assert res.status_code == 401
    assert res.json()["code"] == "guest_token_inactive"
    reactivate.assert_not_called()


def test_new_account_checks_are_registered_under_deliveries_perform():
    from app.authz import grant_keys as g
    from app.authz.grant_sections import GRANT_SECTIONS

    sections = [s["section"] for s in GRANT_SECTIONS[g.DELIVERIES_PERFORM]]
    assert any(s.startswith("POST /delivery/report-failed") for s in sections)
    assert any(s.startswith("POST /delivery/route-legs") for s in sections)
