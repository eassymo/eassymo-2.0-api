"""Router wiring for group-scoped WhatsApp intake member endpoints."""

import pytest
from bson.errors import InvalidId
from fastapi import HTTPException
from unittest.mock import MagicMock, patch

from app.routers.UserRouter import (
    WhatsappIntakeStartRequest,
    whatsapp_intake_start,
    whatsapp_intake_status,
)

SERVICE = "app.routers.UserRouter.WhatsappIntakeVerificationService"
BELONGS = "app.dependencies.group_auth.user_belongs_to_group"


def _request(uid="u1", group=None):
    request = MagicMock()
    request.state.user = {"uid": uid}
    request.state.groupSelected = None
    request.headers = {"groupselected": group} if group else {}
    return request


@patch(BELONGS, return_value=True)
@patch(SERVICE)
def test_status_uses_group_from_header(mock_service, _member):
    mock_service.return_value.get_status.return_value = {"linked": False}
    response = whatsapp_intake_status(_request(group="g1"))
    mock_service.return_value.get_status.assert_called_once_with("u1", "g1")
    assert response.status_code == 200


@patch(BELONGS, return_value=True)
@patch(SERVICE)
def test_start_uses_group_from_header(mock_service, _member):
    mock_service.return_value.start.return_value = {"ok": True}
    whatsapp_intake_start(_request(group="g1"), WhatsappIntakeStartRequest(phone="7779313704"))
    mock_service.return_value.start.assert_called_once_with("u1", "g1", "7779313704")


@patch(SERVICE)
def test_missing_group_header_returns_400(mock_service):
    with pytest.raises(HTTPException) as exc:
        whatsapp_intake_status(_request())
    assert exc.value.status_code == 400
    mock_service.return_value.get_status.assert_not_called()


@patch(BELONGS, return_value=False)
@patch(SERVICE)
def test_non_member_returns_403(mock_service, _member):
    with pytest.raises(HTTPException) as exc:
        whatsapp_intake_status(_request(group="g1"))
    assert exc.value.status_code == 403
    mock_service.return_value.get_status.assert_not_called()
    with pytest.raises(HTTPException) as exc:
        whatsapp_intake_start(_request(group="g1"), WhatsappIntakeStartRequest(phone="1"))
    assert exc.value.status_code == 403
    mock_service.return_value.start.assert_not_called()


@patch(BELONGS, side_effect=InvalidId("bad"))
@patch(SERVICE)
def test_garbage_group_header_is_4xx_not_500(mock_service, _member):
    with pytest.raises(HTTPException) as exc:
        whatsapp_intake_status(_request(group="not-an-objectid"))
    assert 400 <= exc.value.status_code < 500
    assert exc.value.detail == "La tienda seleccionada no es válida."
    mock_service.return_value.get_status.assert_not_called()
