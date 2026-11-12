from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bson.errors import InvalidId

from app.services import access_policy
from app.services.access_policy import PERMISSION_WHATSAPP_CREATE_DRAFT as PERM, can


def _roles(*codes):
    return [SimpleNamespace(role=c) for c in codes]


@pytest.fixture
def mocks():
    with patch("app.services.access_policy.group_auth") as ga, patch(
        "app.services.access_policy.userRolesRepository"
    ) as ur:
        ga.user_belongs_to_group.return_value = True
        ga.is_group_owner.return_value = False
        ur.find.return_value = []
        yield ga, ur


def test_owner_passes_without_role_row(mocks):
    ga, ur = mocks
    ga.is_group_owner.return_value = True
    assert can("u", "g", PERM) is True


@pytest.mark.parametrize("role", ["212", "213"])
def test_listed_role_passes(mocks, role):
    mocks[1].find.return_value = _roles(role)
    assert can("u", "g", PERM) is True


def test_unlisted_role_fails(mocks):
    mocks[1].find.return_value = _roles("215")
    assert can("u", "g", PERM) is False


def test_no_role_row_fails(mocks):
    assert can("u", "g", PERM) is False


def test_non_member_fails(mocks):
    ga, ur = mocks
    ga.user_belongs_to_group.return_value = False
    ga.is_group_owner.return_value = True
    ur.find.return_value = _roles("212")
    assert can("u", "g", PERM) is False


def test_unknown_permission_fails_for_listed_role(mocks):
    mocks[1].find.return_value = _roles("212")
    assert can("u", "g", "whatsapp.nope") is False


@pytest.mark.parametrize("uid,gid", [("", "g"), ("u", ""), ("", "")])
def test_empty_inputs_fail(mocks, uid, gid):
    mocks[0].is_group_owner.return_value = True
    assert can(uid, gid, PERM) is False


def test_roles_lookup_filters_active_rows(mocks):
    mocks[1].find.return_value = _roles("212")
    can("u", "g", PERM)
    mocks[1].find.assert_called_once_with(
        {"user_uid": "u", "group": "g", "active": True}
    )


def test_malformed_group_id_returns_false(mocks):
    mocks[0].user_belongs_to_group.side_effect = InvalidId("bad")
    assert can("u", "not-an-id", PERM) is False


def test_role_table():
    assert access_policy.ROLE_PERMISSIONS == {
        "212": frozenset({PERM}),
        "213": frozenset({PERM}),
    }
