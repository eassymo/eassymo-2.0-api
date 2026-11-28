from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.services import authz

GID = str(ObjectId())

ROLES = {
    "212": {"value": "212", "grants": ["whatsapp.create_draft", "offers.create", "team.view"]},
    "213": {"value": "213", "grants": ["whatsapp.create_draft", "offers.create"]},
    "215": {"value": "215", "grants": ["deliveries.perform", "chat.private"]},
    "off": {"value": "off", "grants": ["reports.view"], "active": False},
    "adm": {"value": "adm", "grants": ["team.assign_roles", "team.view", "offers.create"],
            "assignable_by_group_admins": True, "entity_types": ["1"]},
    "big": {"value": "big", "grants": ["offers.create", "prices.view"],
            "assignable_by_group_admins": True, "entity_types": ["1", "2"]},
    "hid": {"value": "hid", "grants": ["offers.create"], "assignable_by_group_admins": False},
    "eas": {"value": "eas", "grants": ["eassymo.uom"], "assignable_by_group_admins": True},
}
ACTIVE = {"whatsapp.create_draft", "offers.create", "team.view", "deliveries.perform",
          "chat.private", "reports.view", "team.assign_roles", "prices.view", "eassymo.uom"}


@pytest.fixture
def env():
    with patch.object(authz, "group_auth") as ga, \
         patch.object(authz, "userRolesRepository") as ur, \
         patch.object(authz, "RolesRepository") as rr, \
         patch.object(authz, "GrantRepository") as gr, \
         patch.object(authz, "groupRepository") as grp:
        ga.user_belongs_to_group.return_value = True
        ga.is_group_owner.return_value = False
        ur.find.return_value = []
        rr.find_by_values.side_effect = lambda vals: [ROLES[v] for v in vals if v in ROLES]
        rr.find_by_value.side_effect = lambda v: ROLES.get(v)
        gr.active_keys.return_value = set(ACTIVE)
        # Group type 2 = SELLER (Refaccionaria): fits "adm", whose entity_types ["1"] is census Refaccionaria.
        grp.find_by_id.return_value = {"_id": GID, "type": 2}
        yield SimpleNamespace(ga=ga, ur=ur, rr=rr, gr=gr, grp=grp)


def _rows(*roles):
    return [SimpleNamespace(role=r) for r in roles]


def test_union_of_roles(env):
    env.ur.find.return_value = _rows("212", "215")
    assert authz.effective_grants("u", GID) == frozenset(
        {"whatsapp.create_draft", "offers.create", "team.view", "deliveries.perform", "chat.private"})
    env.ur.find.assert_called_once_with({"user_uid": "u", "group": GID, "active": True})


def test_inactive_role_ignored(env):
    env.ur.find.return_value = _rows("off")
    assert authz.effective_grants("u", GID) == frozenset()


def test_inactive_grant_dropped(env):
    env.ur.find.return_value = _rows("212")
    env.gr.active_keys.return_value = ACTIVE - {"team.view"}
    assert "team.view" not in authz.effective_grants("u", GID)


def test_owner_gets_all_active_but_eassymo(env):
    env.ga.is_group_owner.return_value = True
    grants = authz.effective_grants("o", GID)
    assert grants == frozenset(ACTIVE - {"eassymo.uom"})


def test_eassymo_grants_never_come_from_a_role(env):
    env.ur.find.return_value = _rows("eas")
    assert authz.effective_grants("u", GID) == frozenset()


def test_non_member_gets_nothing(env):
    env.ga.user_belongs_to_group.return_value = False
    env.ga.is_group_owner.return_value = True
    assert authz.effective_grants("u", GID) == frozenset()


def test_invalid_group_gets_nothing(env):
    env.ga.user_belongs_to_group.side_effect = InvalidId("bad")
    assert authz.effective_grants("u", "bad") == frozenset()


@pytest.mark.parametrize("uid,gid", [("", GID), ("u", ""), (None, None)])
def test_empty_inputs(env, uid, gid):
    assert authz.effective_grants(uid, gid) == frozenset()


def test_memoized_per_request(env):
    env.ur.find.return_value = _rows("212")
    request = SimpleNamespace(state=SimpleNamespace())
    authz.effective_grants("u", GID, request)
    authz.effective_grants("u", GID, request)
    assert env.ur.find.call_count == 1


@pytest.mark.parametrize("role,expected", [("212", True), ("213", True), ("215", False)])
def test_can_whatsapp_draft(env, role, expected):
    env.ur.find.return_value = _rows(role)
    assert authz.can("u", GID, "whatsapp.create_draft") is expected


def _request(uid="u", group=GID):
    req = MagicMock()
    req.state = SimpleNamespace(user={"uid": uid} if uid else None, groupSelected=group)
    req.headers = {}
    return req


def test_require_grant_403_names_key(env):
    env.ur.find.return_value = _rows("215")
    dep = authz.require_grant("offers.create")
    with pytest.raises(HTTPException) as exc:
        dep(_request())
    assert exc.value.status_code == 403
    assert "offers.create" in exc.value.detail


def test_require_grant_passes_and_returns_group(env):
    env.ur.find.return_value = _rows("212")
    assert authz.require_grant("offers.create", "team.view")(_request()) == GID


def test_require_grant_401_without_user(env):
    with pytest.raises(HTTPException) as exc:
        authz.require_grant("offers.create")(_request(uid=None))
    assert exc.value.status_code == 401


def test_selected_group_invalid_is_400(env):
    with pytest.raises(HTTPException) as exc:
        authz.selected_group(_request(group="not-an-id"))
    assert exc.value.status_code == 400


def test_selected_group_missing_is_400(env):
    with pytest.raises(HTTPException) as exc:
        authz.selected_group(_request(group=None))
    assert exc.value.status_code == 400


# ── can_assign_role ─────────────────────────────────────────────────────────

def test_owner_can_assign_assignable_role(env):
    env.ga.is_group_owner.return_value = True
    assert authz.can_assign_role("o", GID, "big") == (True, "")


def test_admin_cannot_escalate(env):
    env.ur.find.return_value = _rows("adm")
    ok, reason = authz.can_assign_role("u", GID, "big")
    assert ok is False and "prices.view" in reason


def test_admin_can_assign_subset(env):
    env.ur.find.return_value = _rows("adm")
    env.rr.find_by_value.side_effect = lambda v: {"value": "sub", "grants": ["offers.create"],
                                                  "assignable_by_group_admins": True}
    assert authz.can_assign_role("u", GID, "sub") == (True, "")


def test_owner_may_assign_non_assignable_role_like_before(env):
    env.ga.is_group_owner.return_value = True
    assert authz.can_assign_role("o", GID, "hid") == (True, "")


def test_non_owner_cannot_assign_non_assignable_role(env):
    env.ur.find.return_value = _rows("adm")
    assert authz.can_assign_role("u", GID, "hid")[0] is False


def test_member_with_team_invite_can_invite_with_subset_role(env):
    # Legacy members hold team.invite but not team.assign_roles; inviting must keep working.
    env.rr.find_by_value.side_effect = lambda v: {"value": "213", "grants": ["offers.create"],
                                                  "assignable_by_group_admins": True}
    with patch.object(authz, "effective_grants", return_value=frozenset({"team.invite", "offers.create"})):
        assert authz.can_invite_with_role("u", GID, "213") == (True, "")
        assert authz.can_assign_role("u", GID, "213")[0] is False


def test_invite_cannot_escalate(env):
    with patch.object(authz, "effective_grants", return_value=frozenset({"team.invite", "offers.create"})):
        ok, reason = authz.can_invite_with_role("u", GID, "big")
    assert ok is False and "prices.view" in reason


def test_wrong_entity_type_denied(env):
    env.ga.is_group_owner.return_value = True
    # A Taller (group type 1, BUYER) cannot take a Refaccionaria-only role.
    env.grp.find_by_id.return_value = {"_id": GID, "type": 1}
    assert authz.can_assign_role("o", GID, "adm")[0] is False


def test_eassymo_role_denied(env):
    env.ga.is_group_owner.return_value = True
    assert authz.can_assign_role("o", GID, "eas")[0] is False


def test_member_without_assign_grant_denied(env):
    env.ur.find.return_value = _rows("212")
    assert authz.can_assign_role("u", GID, "hid")[0] is False
    env.rr.find_by_value.side_effect = lambda v: {"value": "x", "grants": ["offers.create"],
                                                  "assignable_by_group_admins": True}
    assert authz.can_assign_role("u", GID, "x")[0] is False


def test_unknown_or_inactive_role_denied(env):
    env.ga.is_group_owner.return_value = True
    assert authz.can_assign_role("o", GID, "nope")[0] is False
    assert authz.can_assign_role("o", GID, "off")[0] is False


def test_unmigrated_legacy_role_keeps_todays_grants(env):
    env.ur.find.return_value = _rows("212")
    env.rr.find_by_values.side_effect = lambda vals: [{"value": 212}]  # stored as a number, no grants field
    env.gr.active_keys.return_value = set(ACTIVE)
    assert "whatsapp.create_draft" in authz.effective_grants("u", GID)


def test_unseeded_catalog_counts_every_known_key_as_active(env):
    from app.authz.grant_keys import ALL_KEYS

    env.ga.is_group_owner.return_value = True
    env.gr.active_keys.return_value = set()
    env.gr.find.return_value = []
    assert authz.effective_grants("o", GID) == frozenset(k for k in ALL_KEYS if not k.startswith("eassymo."))


def test_seeded_catalog_with_everything_inactive_stays_empty(env):
    env.ga.is_group_owner.return_value = True
    env.gr.active_keys.return_value = set()
    env.gr.find.return_value = [{"key": "offers.create", "active": False}]
    assert authz.effective_grants("o", GID) == frozenset()


# ── Super Admin role (all_grants) ───────────────────────────────────────────

SUPER = {"value": "super_admin", "all_grants": True, "grants": [], "is_system": True}


def _with_super(env):
    base = env.rr.find_by_values.side_effect
    env.rr.find_by_values.side_effect = lambda vals: ([SUPER] if "super_admin" in vals else []) + base(vals)
    env.rr.find_by_value.side_effect = lambda v: SUPER if v == "super_admin" else ROLES.get(v)


def test_super_admin_role_gets_every_active_grant_including_eassymo(env):
    _with_super(env)
    env.ur.find.return_value = _rows("super_admin")
    assert authz.effective_grants("u", GID) == frozenset(ACTIVE)


def test_super_admin_role_adds_eassymo_for_owner_too(env):
    _with_super(env)
    env.ga.is_group_owner.return_value = True
    env.ur.find.return_value = _rows("super_admin")
    assert "eassymo.uom" in authz.effective_grants("o", GID)


def test_super_admin_role_still_requires_membership(env):
    _with_super(env)
    env.ga.user_belongs_to_group.return_value = False
    env.ur.find.return_value = _rows("super_admin")
    assert authz.effective_grants("u", GID) == frozenset()


def test_inactive_super_admin_role_gives_nothing(env):
    env.rr.find_by_values.side_effect = lambda vals: [{**SUPER, "active": False}]
    env.ur.find.return_value = _rows("super_admin")
    assert authz.effective_grants("u", GID) == frozenset()


def test_nobody_can_delegate_the_super_admin_role(env):
    _with_super(env)
    env.ga.is_group_owner.return_value = True
    assert authz.can_assign_role("o", GID, "super_admin")[0] is False
    assert authz.can_invite_with_role("o", GID, "super_admin")[0] is False
