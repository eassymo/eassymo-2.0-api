"""Authorization and security invariant tests."""

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock, patch

from app.dependencies.group_auth import (
    authorize_role_mutation,
    assert_group_membership,
    is_group_owner,
    user_belongs_to_group,
)
from main import CORS_ALLOW_ORIGINS, CORS_LOCALHOST_REGEX


def _request_with_user(uid: str):
    request = MagicMock()
    request.state.user = {"uid": uid}
    return request


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
def test_is_group_owner_true_when_caller_matches_owner(mock_find):
    mock_find.return_value = {"owner": "owner-1", "users": []}
    assert is_group_owner("owner-1", "group-1") is True


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
def test_authorize_role_mutation_allows_group_owner(mock_find):
    mock_find.return_value = {"owner": "owner-1", "users": ["member-1"]}
    request = _request_with_user("owner-1")
    authorize_role_mutation(request, "member-1", "group-1")


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
def test_authorize_role_mutation_denies_non_owner(mock_find):
    mock_find.return_value = {"owner": "owner-1", "users": ["member-1"]}
    request = _request_with_user("member-1")
    with pytest.raises(HTTPException) as exc:
        authorize_role_mutation(request, "other-member", "group-1")
    assert exc.value.status_code == 403


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
def test_authorize_role_mutation_allows_self_pre_group_role(mock_find):
    mock_find.return_value = None
    request = _request_with_user("user-1")
    authorize_role_mutation(request, "user-1", None)


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
def test_authorize_role_mutation_denies_other_user_without_group(mock_find):
    mock_find.return_value = None
    request = _request_with_user("user-1")
    with pytest.raises(HTTPException) as exc:
        authorize_role_mutation(request, "user-2", None)
    assert exc.value.status_code == 403


@patch("app.dependencies.group_auth.userRolesRepository.find")
@patch("app.dependencies.group_auth.userRepository.find_one")
@patch("app.dependencies.group_auth.groupRepository.find_by_id")
def test_user_belongs_to_group_via_group_users(mock_find_group, mock_find_user, mock_find_roles):
    mock_find_group.return_value = {"owner": "owner-1", "users": ["member-1"]}
    mock_find_user.return_value = None
    mock_find_roles.return_value = []
    assert user_belongs_to_group("member-1", "group-1") is True


@patch("app.dependencies.group_auth.userRolesRepository.find")
@patch("app.dependencies.group_auth.userRepository.find_one")
@patch("app.dependencies.group_auth.groupRepository.find_by_id")
def test_assert_group_membership_denies_outsider(mock_find_group, mock_find_user, mock_find_roles):
    mock_find_group.return_value = {"owner": "owner-1", "users": []}
    mock_find_user.return_value = {"uid": "outsider", "groups": []}
    mock_find_roles.return_value = []
    with pytest.raises(HTTPException) as exc:
        assert_group_membership("outsider", "group-1")
    assert exc.value.status_code == 403


def test_cors_allowlist_is_not_wildcard():
    assert "*" not in CORS_ALLOW_ORIGINS
    assert "localhost" in CORS_LOCALHOST_REGEX
