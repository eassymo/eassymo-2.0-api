"""Owner enable/disable endpoints for WhatsApp links."""

import json
from unittest.mock import MagicMock, patch

from bson.errors import InvalidId

from app.routers import WhatsappLinksRouter as router

GROUP = "g1"


def _request(uid="owner-1"):
    request = MagicMock()
    request.state.user = {"uid": uid}
    return request


def _owner_doc():
    return {"owner": "owner-1", "users": ["member-1"]}


def _body(response):
    return json.loads(response.body)


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
@patch("app.routers.WhatsappLinksRouter.link_repo")
def test_owner_can_disable(mock_repo, mock_group):
    mock_group.return_value = _owner_doc()
    mock_repo.find.return_value = {"uid": "member-1", "group_id": GROUP, "status": "active"}
    resp = router.disable_link(_request(), GROUP, "member-1")
    assert resp.status_code == 200
    assert _body(resp)["body"] == {"uid": "member-1", "group_id": GROUP, "status": "disabled"}


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
@patch("app.routers.WhatsappLinksRouter.link_repo")
def test_owner_can_enable(mock_repo, mock_group):
    mock_group.return_value = _owner_doc()
    mock_repo.find.return_value = {"uid": "member-1", "group_id": GROUP, "status": "disabled"}
    resp = router.enable_link(_request(), GROUP, "member-1")
    assert resp.status_code == 200
    assert _body(resp)["body"]["status"] == "active"
    mock_repo.set_status.assert_called_once_with("member-1", GROUP, "active", "owner-1")


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
@patch("app.routers.WhatsappLinksRouter.link_repo")
def test_non_owner_gets_403(mock_repo, mock_group):
    mock_group.return_value = _owner_doc()
    resp = router.disable_link(_request("member-1"), GROUP, "member-1")
    assert resp.status_code == 403
    mock_repo.set_status.assert_not_called()


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
@patch("app.routers.WhatsappLinksRouter.link_repo")
def test_unknown_link_gets_404(mock_repo, mock_group):
    mock_group.return_value = _owner_doc()
    mock_repo.find.return_value = None
    resp = router.disable_link(_request(), GROUP, "ghost")
    assert resp.status_code == 404
    mock_repo.set_status.assert_not_called()


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
@patch("app.routers.WhatsappLinksRouter.link_repo")
def test_disable_records_caller_as_disabled_by(mock_repo, mock_group):
    mock_group.return_value = _owner_doc()
    mock_repo.find.return_value = {"uid": "member-1", "group_id": GROUP}
    router.disable_link(_request(), GROUP, "member-1")
    mock_repo.set_status.assert_called_once_with("member-1", GROUP, "disabled", "owner-1")


@patch("app.dependencies.group_auth.groupRepository.find_by_id")
@patch("app.routers.WhatsappLinksRouter.link_repo")
def test_malformed_group_id_gets_400(mock_repo, mock_group):
    mock_group.side_effect = InvalidId("bad")
    resp = router.disable_link(_request(), "garbage", "member-1")
    assert resp.status_code == 400
    mock_repo.set_status.assert_not_called()
