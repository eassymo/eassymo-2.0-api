from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.routers import MeRouter

GID = str(ObjectId())
OTHER = str(ObjectId())


def _request(group=GID):
    return SimpleNamespace(state=SimpleNamespace(user={"uid": "u"}, groupSelected=group), headers={})


@patch.object(MeRouter.group_auth, "is_group_owner", return_value=False)
@patch.object(MeRouter.authz, "effective_grants", return_value=frozenset({"offers.create", "chat.private"}))
def test_returns_sorted_grants_for_header_group(eff, owner):
    with patch.object(MeRouter.group_auth, "user_belongs_to_group", return_value=True):
        body = MeRouter.my_grants(_request(), group_id=None)
    assert body == {"body": {"group_id": GID, "is_owner": False, "grants": ["chat.private", "offers.create"]}}
    assert eff.call_args[0][:2] == ("u", GID)


@patch.object(MeRouter.group_auth, "is_group_owner", return_value=True)
@patch.object(MeRouter.authz, "effective_grants", return_value=frozenset())
def test_query_param_overrides_header(eff, owner):
    with patch.object(MeRouter.group_auth, "user_belongs_to_group", return_value=True):
        body = MeRouter.my_grants(_request(), group_id=OTHER)
    assert body["body"]["group_id"] == OTHER
    assert body["body"]["is_owner"] is True


def test_missing_group_is_400():
    with pytest.raises(HTTPException) as exc:
        MeRouter.my_grants(_request(group=None), group_id=None)
    assert exc.value.status_code == 400


@patch.object(MeRouter.group_auth, "is_group_owner", return_value=True)
@patch.object(MeRouter.authz, "effective_grants", return_value=frozenset())
def test_non_member_owner_flag_false(eff, owner):
    # effective_grants is empty for non-members; is_owner must not claim ownership then
    with patch.object(MeRouter.group_auth, "user_belongs_to_group", return_value=False):
        body = MeRouter.my_grants(_request(), group_id=None)
    assert body["body"]["is_owner"] is False
