import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.dependencies import group_auth
from app.routers import RolesRouter, TeamMemberInviteRouter
from app.schemas.TeamMemberInvite import TeamMemberInvite
from app.services import authz

GID = str(ObjectId())
ROLE_OID = str(ObjectId())


def _request(uid="caller", group=GID):
    req = MagicMock()
    req.state = SimpleNamespace(user={"uid": uid}, groupSelected=group)
    req.headers = {}
    return req


# ── authorize_role_mutation ─────────────────────────────────────────────────

def test_mutation_with_role_uses_can_assign_role():
    with patch.object(authz, "can_assign_role", return_value=(True, "")) as car, \
         patch.object(group_auth, "is_group_owner", return_value=False):
        group_auth.authorize_role_mutation(_request(), "member", GID, "213")
    car.assert_called_once()
    assert car.call_args[0][:3] == ("caller", GID, "213")


def test_mutation_denied_with_reason():
    with patch.object(authz, "can_assign_role", return_value=(False, "No puedes asignar")), \
         patch.object(group_auth, "is_group_owner", return_value=False):
        with pytest.raises(HTTPException) as exc:
            group_auth.authorize_role_mutation(_request(), "member", GID, "213")
    assert exc.value.status_code == 403
    assert exc.value.detail == "No puedes asignar"


def test_owner_activating_own_role_skips_assignable_check():
    with patch.object(authz, "can_assign_role") as car, \
         patch.object(group_auth, "is_group_owner", return_value=True):
        group_auth.authorize_role_mutation(_request(uid="o"), "o", GID, "212", owner_self_activation=True)
    car.assert_not_called()


def test_resolve_role_value_accepts_id_or_value():
    with patch.object(authz.RolesRepository, "find_by_id", return_value={"value": "213"}):
        assert authz.resolve_role_value(ROLE_OID) == "213"
    assert authz.resolve_role_value("213") == "213"
    assert authz.resolve_role_value(None) is None


# ── invites ─────────────────────────────────────────────────────────────────

def _invite(**kw):
    return TeamMemberInvite(**{"group": GID, "role": ROLE_OID, "inviter_user": "someone-else",
                               "contact_method": "+520000000000", **kw})


def _body(resp):
    return resp.status_code, json.loads(resp.body)


def test_invite_without_team_invite_grant_is_403():
    with patch.object(TeamMemberInviteRouter.authz, "resolve_role_value", return_value="213"), \
         patch.object(TeamMemberInviteRouter.authz, "can_invite_with_role", return_value=(False, "Missing grant: team.invite")), \
         patch.object(TeamMemberInviteRouter.teamMemberInviteService, "insert") as ins:
        status, _ = _body(TeamMemberInviteRouter.insert(_request(), _invite()))
    assert status == 403
    ins.assert_not_called()


def test_invite_with_unassignable_role_is_403():
    with patch.object(TeamMemberInviteRouter.authz, "effective_grants", return_value=frozenset({"team.invite"})), \
         patch.object(TeamMemberInviteRouter.authz, "resolve_role_value", return_value="322"), \
         patch.object(TeamMemberInviteRouter.authz, "can_invite_with_role", return_value=(False, "nope")), \
         patch.object(TeamMemberInviteRouter.teamMemberInviteService, "insert") as ins:
        status, _ = _body(TeamMemberInviteRouter.insert(_request(), _invite()))
    assert status == 403
    ins.assert_not_called()


def test_invite_ok_forces_inviter_to_caller():
    with patch.object(TeamMemberInviteRouter.authz, "effective_grants", return_value=frozenset({"team.invite"})), \
         patch.object(TeamMemberInviteRouter.authz, "resolve_role_value", return_value="213"), \
         patch.object(TeamMemberInviteRouter.authz, "can_invite_with_role", return_value=(True, "")), \
         patch.object(TeamMemberInviteRouter.teamMemberInviteService, "insert", return_value={"invite_id": "x"}) as ins:
        status, _ = _body(TeamMemberInviteRouter.insert(_request(), _invite()))
    assert status == 200
    assert ins.call_args[0][0].inviter_user == "caller"


def test_accept_rechecks_role_and_blocks_when_no_longer_assignable():
    invite_doc = {"_id": ObjectId(), "group": GID, "role": ROLE_OID, "inviter_user": "boss"}
    with patch.object(TeamMemberInviteRouter.teamMemberInviteRepository, "find_by_id", return_value=invite_doc), \
         patch.object(TeamMemberInviteRouter.authz, "resolve_role_value", return_value="213"), \
         patch.object(TeamMemberInviteRouter.authz, "role_fits_group", return_value=(None, "x")) as fits, \
         patch.object(TeamMemberInviteRouter.teamMemberInviteService, "change_invite_status") as chg:
        status, _ = _body(TeamMemberInviteRouter.accept_team_member_invite(str(invite_doc["_id"]), {"user_uid": "new"}))
    assert status == 403
    assert fits.call_args[0] == (GID, "213")
    chg.assert_not_called()


def test_accept_does_not_depend_on_inviter_grants():
    invite_doc = {"_id": ObjectId(), "group": GID, "role": ROLE_OID, "inviter_user": "former-member"}
    with patch.object(TeamMemberInviteRouter.teamMemberInviteRepository, "find_by_id", return_value=invite_doc), \
         patch.object(TeamMemberInviteRouter.authz, "resolve_role_value", return_value="213"), \
         patch.object(TeamMemberInviteRouter.authz, "role_fits_group", return_value=({"value": "213"}, "")), \
         patch.object(TeamMemberInviteRouter.authz, "effective_grants", return_value=frozenset()), \
         patch.object(TeamMemberInviteRouter.teamMemberInviteService, "change_invite_status", return_value={"ok": True}):
        status, _ = _body(TeamMemberInviteRouter.accept_team_member_invite(str(invite_doc["_id"]), {"user_uid": "new"}))
    assert status == 200


# ── assignable roles ────────────────────────────────────────────────────────

def test_roles_assignable_filters_by_can_assign():
    roles = [{"_id": ObjectId(), "value": "213", "display": True},
             {"_id": ObjectId(), "value": "tpl.v.admin", "display": False}]
    with patch.object(RolesRouter.rolesRepository, "find", return_value=roles), \
         patch.object(RolesRouter.authz, "can_assign_role",
                      side_effect=lambda uid, gid, value, request=None: (value == "tpl.v.admin", "")), \
         patch.object(RolesRouter.authz, "can_invite_with_role", return_value=(False, "")):
        resp = RolesRouter.find(_request(), assignable=True, all=False)
    values = [r["value"] for r in json.loads(resp.body)]
    assert values == ["tpl.v.admin"]


def test_roles_default_unchanged():
    with patch.object(RolesRouter.rolesService, "find_roles", return_value=[{"value": "213"}]):
        resp = RolesRouter.find(_request(), assignable=False, all=False)
    assert json.loads(resp.body) == [{"value": "213"}]


def test_roles_all_returns_every_active_role():
    roles = [{"_id": ObjectId(), "value": "tpl.v.admin", "display": False}]
    with patch.object(RolesRouter.rolesRepository, "find", return_value=roles) as find:
        resp = RolesRouter.find(_request(), assignable=False, all=True)
    assert [r["value"] for r in json.loads(resp.body)] == ["tpl.v.admin"]
    assert find.call_args[0][0] == {"active": {"$ne": False}}
