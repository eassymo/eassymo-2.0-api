from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import WhatsappFolioThreadService as thread_service


def _folio(**overrides):
    doc = {
        "_id": "folio-1",
        "source": "whatsapp",
        "origin_group_id": "g1",
        "invited_shops": [],
    }
    doc.update(overrides)
    return doc


@patch("app.services.WhatsappFolioThreadService.inbound_repo")
@patch("app.services.WhatsappFolioThreadService.folioRepository")
def test_get_whatsapp_thread_groups_by_burst_id(mock_folio_repo, mock_inbound_repo):
    mock_folio_repo.find_by_id.return_value = _folio()
    mock_inbound_repo.list_by_folio_id.return_value = [
        {
            "_id": "1",
            "burst_id": "burst-a",
            "direction": "inbound",
            "kind": "content",
            "body": "Koleos 2020 faro",
            "forwarded": True,
            "created_at": "2026-03-20T12:38:00+00:00",
            "from_number": "+5217779313704",
        },
        {
            "_id": "2",
            "burst_id": "burst-a",
            "direction": "outbound",
            "kind": "bot_draft",
            "body": "Borrador listo en Eassymo POS.",
            "forwarded": False,
            "created_at": "2026-03-20T12:39:00+00:00",
        },
        {
            "_id": "3",
            "burst_id": "burst-b",
            "direction": "inbound",
            "kind": "content",
            "body": "también calavera",
            "forwarded": True,
            "created_at": "2026-03-20T14:02:00+00:00",
        },
    ]

    result = thread_service.get_whatsapp_thread("folio-1", "g1")

    assert result["from_number_last4"] == "3704"
    assert len(result["bursts"]) == 2
    assert result["bursts"][0]["burst_id"] == "burst-a"
    assert len(result["bursts"][0]["events"]) == 2
    assert result["bursts"][0]["events"][0]["forwarded"] is True


@patch("app.services.WhatsappFolioThreadService.inbound_repo")
@patch("app.services.WhatsappFolioThreadService.folioRepository")
def test_get_whatsapp_thread_includes_linked_reaction(mock_folio_repo, mock_inbound_repo):
    mock_folio_repo.find_by_id.return_value = _folio()
    mock_inbound_repo.list_by_folio_id.return_value = [
        {
            "_id": "1",
            "burst_id": "burst-a",
            "direction": "inbound",
            "kind": "content",
            "body": "balatas versa 2018",
            "forwarded": True,
            "created_at": "2026-03-20T12:38:00+00:00",
            "linked_reaction": {
                "emoji": "🔗",
                "method": "fallback",
                "folio_code": "ABC123",
            },
        }
    ]

    result = thread_service.get_whatsapp_thread("folio-1", "g1")
    event = result["bursts"][0]["events"][0]
    assert event["linked_reaction"]["folio_code"] == "ABC123"


@patch("app.services.WhatsappFolioThreadService.folioRepository")
def test_get_whatsapp_thread_rejects_non_whatsapp_folio(mock_folio_repo):
    mock_folio_repo.find_by_id.return_value = _folio(source="counter")

    with pytest.raises(HTTPException) as exc:
        thread_service.get_whatsapp_thread("folio-1", "g1")

    assert exc.value.status_code == 404


@patch("app.services.WhatsappFolioThreadService.folioRepository")
def test_get_whatsapp_thread_rejects_wrong_group(mock_folio_repo):
    mock_folio_repo.find_by_id.return_value = _folio(origin_group_id="g1")

    with pytest.raises(HTTPException) as exc:
        thread_service.get_whatsapp_thread("folio-1", "g-other")

    assert exc.value.status_code == 403


@patch("app.services.WhatsappFolioThreadService.inbound_repo")
@patch("app.services.WhatsappFolioThreadService.folioRepository")
def test_get_whatsapp_thread_legacy_gap_fallback(mock_folio_repo, mock_inbound_repo):
    mock_folio_repo.find_by_id.return_value = _folio()
    mock_inbound_repo.list_by_folio_id.return_value = [
        {
            "_id": "1",
            "direction": "inbound",
            "body": "Jetta 2015",
            "forwarded": True,
            "created_at": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc).isoformat(),
        },
        {
            "_id": "2",
            "direction": "inbound",
            "body": "filtro de aire",
            "forwarded": True,
            "created_at": datetime(2026, 3, 20, 12, 1, tzinfo=timezone.utc).isoformat(),
        },
        {
            "_id": "3",
            "direction": "inbound",
            "body": "calavera",
            "forwarded": True,
            "created_at": datetime(2026, 3, 20, 14, 0, tzinfo=timezone.utc).isoformat(),
        },
    ]

    result = thread_service.get_whatsapp_thread("folio-1", "g1")

    assert len(result["bursts"]) == 2
    assert len(result["bursts"][0]["events"]) == 2
    assert len(result["bursts"][1]["events"]) == 1
