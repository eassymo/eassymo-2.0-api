import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.WhatasppMessage import WhatsappMessage, WhatsappTemplate
from app.services.NetworkService import _network_invite_template
from app.services.TeamMemberInviteService import _team_invite_template
from app.services.WhatsappInboundService import WhatsappInboundService
from app.services.WhatsappService import DELIVERY_INVITE_FREEFORM, WhatsappService


def _meta_text_webhook(
    *,
    message_id="wamid.TEXT1",
    from_number="5217779313704",
    body="Jetta 2015, filtro de aire",
    profile_name="Ian",
    display_phone_number="5216141115669",
    context=None,
):
    message = {
        "from": from_number,
        "id": message_id,
        "timestamp": "1710000000",
        "type": "text",
        "text": {"body": body},
    }
    if context is not None:
        message["context"] = context
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA123",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": display_phone_number,
                                "phone_number_id": "1260808447123551",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": profile_name},
                                    "wa_id": from_number,
                                }
                            ],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def _meta_status_webhook(message_id="wamid.OUT1", status="delivered"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA123",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5216141115669",
                                "phone_number_id": "1260808447123551",
                            },
                            "statuses": [
                                {
                                    "id": message_id,
                                    "status": status,
                                    "timestamp": "1710000001",
                                    "recipient_id": "5217779313704",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _signed_request(secret: str, raw_body: bytes):
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return SimpleNamespace(headers={"X-Hub-Signature-256": f"sha256={digest}"})


def _cloud_service(monkeypatch) -> WhatsappService:
    monkeypatch.setenv("WHATSAPP_CLOUD_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_CLOUD_PHONE_NUMBER_ID", "123456")
    monkeypatch.setenv("WHATSAPP_CLOUD_API_VERSION", "v21.0")
    monkeypatch.setenv("WHATSAPP_TEMPLATE_LANGUAGE", "es_MX")
    return WhatsappService()


def _graph_ok(message_id="wamid.SENT1"):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"messages": [{"id": message_id}]}
    response.text = json.dumps({"messages": [{"id": message_id}]})
    return response


def test_parse_meta_text_normalizes_intake_keys():
    service = WhatsappInboundService()
    body = _meta_text_webhook()
    payloads, statuses = service.extract_webhook_events(body)
    assert statuses == []
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["message_sid"] == "wamid.TEXT1"
    assert payload["whatsapp_message_id"] == "wamid.TEXT1"
    assert payload["from_number"] == "5217779313704"
    assert payload["to_number"] == "5216141115669"
    assert payload["body"] == "Jetta 2015, filtro de aire"
    assert payload["profile_name"] == "Ian"
    assert payload["wa_id"] == "5217779313704"
    assert payload["forwarded"] is False
    assert payload["original_replied_message_sid"] == ""
    assert payload["num_media"] == 0
    assert payload["media_urls"] == []
    assert payload["status"] == "received"
    assert payload["account_sid"] == "WABA123"


def test_parse_meta_reply_context_sets_original_replied_message_sid():
    service = WhatsappInboundService()
    body = _meta_text_webhook(
        body="Delanteras",
        context={"from": "5216141115669", "id": "wamid.CLARIFY1"},
    )
    payloads, _ = service.extract_webhook_events(body)
    assert payloads[0]["original_replied_message_sid"] == "wamid.CLARIFY1"
    assert payloads[0]["forwarded"] is False


def test_parse_meta_forwarded_flag():
    service = WhatsappInboundService()
    body = _meta_text_webhook(
        context={"forwarded": True, "frequently_forwarded": True}
    )
    payloads, _ = service.extract_webhook_events(body)
    assert payloads[0]["forwarded"] is True


def test_parse_meta_skips_reaction_messages():
    service = WhatsappInboundService()
    body = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA123",
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": "5216141115669"},
                            "messages": [
                                {
                                    "from": "5217779313704",
                                    "id": "wamid.REACT1",
                                    "type": "reaction",
                                    "reaction": {
                                        "message_id": "wamid.TEXT1",
                                        "emoji": "👍",
                                    },
                                }
                            ],
                        }
                    }
                ],
            }
        ],
    }
    payloads, statuses = service.extract_webhook_events(body)
    assert payloads == []
    assert statuses == []


def test_parse_meta_image_uses_caption_and_media_id():
    service = WhatsappInboundService()
    value = {
        "metadata": {"display_phone_number": "5216141115669"},
        "contacts": [{"profile": {"name": "Ian"}, "wa_id": "5217779313704"}],
        "messages": [
            {
                "from": "5217779313704",
                "id": "wamid.IMG1",
                "type": "image",
                "image": {"id": "MEDIA123", "caption": "balatas delanteras"},
            }
        ],
    }
    payload = service.parse_meta_message(value["messages"][0], value, account_id="WABA")
    assert payload["body"] == "balatas delanteras"
    assert payload["num_media"] == 1
    assert payload["media_urls"] == ["MEDIA123"]
    assert payload["message_sid"] == "wamid.IMG1"


@patch("app.services.WhatsappInboundService.inbound_repo")
def test_status_only_webhook_does_not_persist_or_process(mock_repo, monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SKIP_SIGNATURE", "true")
    mock_repo.find_by_message_sid.return_value = None
    service = WhatsappInboundService()
    raw = json.dumps(_meta_status_webhook()).encode("utf-8")
    results = service.handle_inbound(SimpleNamespace(headers={}), raw)
    assert results == []
    mock_repo.insert_if_new.assert_not_called()
    mock_repo.update_fields.assert_not_called()


@patch("app.services.WhatsappInboundService.inbound_repo")
def test_status_webhook_updates_existing_message(mock_repo, monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SKIP_SIGNATURE", "true")
    mock_repo.find_by_message_sid.return_value = {"message_sid": "wamid.OUT1"}
    service = WhatsappInboundService()
    raw = json.dumps(_meta_status_webhook(status="read")).encode("utf-8")
    results = service.handle_inbound(SimpleNamespace(headers={}), raw)
    assert results == []
    mock_repo.insert_if_new.assert_not_called()
    mock_repo.update_fields.assert_called_once_with("wamid.OUT1", {"status": "read"})


def test_valid_meta_signature_accepted(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "super-secret")
    monkeypatch.delenv("WHATSAPP_WEBHOOK_SKIP_SIGNATURE", raising=False)
    raw = json.dumps(_meta_text_webhook()).encode("utf-8")
    service = WhatsappInboundService()
    service.validate_signature(_signed_request("super-secret", raw), raw)


def test_invalid_meta_signature_rejected(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "super-secret")
    monkeypatch.delenv("WHATSAPP_WEBHOOK_SKIP_SIGNATURE", raising=False)
    raw = json.dumps(_meta_text_webhook()).encode("utf-8")
    service = WhatsappInboundService()
    with pytest.raises(HTTPException) as exc:
        service.validate_signature(
            SimpleNamespace(headers={"X-Hub-Signature-256": "sha256=deadbeef"}),
            raw,
        )
    assert exc.value.status_code == 403


def test_missing_meta_signature_rejected(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "super-secret")
    monkeypatch.delenv("WHATSAPP_WEBHOOK_SKIP_SIGNATURE", raising=False)
    service = WhatsappInboundService()
    with pytest.raises(HTTPException) as exc:
        service.validate_signature(SimpleNamespace(headers={}), b"{}")
    assert exc.value.status_code == 403


@patch("app.services.WhatsappService.requests.post")
def test_send_text_message_builds_graph_json(mock_post, monkeypatch):
    mock_post.return_value = _graph_ok("wamid.TXT")
    service = _cloud_service(monkeypatch)
    result = service.send_text_message("+5217779313704", "Borrador listo en Eassymo POS.")
    assert result["success"] is True
    assert result["message_sid"] == "wamid.TXT"
    assert result["status"] == "sent"
    assert result["to"] == "+5217779313704"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == "5217779313704"
    assert payload["type"] == "text"
    assert payload["text"]["body"] == "Borrador listo en Eassymo POS."
    assert payload["text"]["preview_url"] is True


@patch("app.services.WhatsappService.requests.post")
def test_send_team_invite_template_variable_order(mock_post, monkeypatch):
    mock_post.return_value = _graph_ok("wamid.TEAM")
    service = _cloud_service(monkeypatch)
    invite_id = "65fca0b3cee797816ade67f7"
    result = service.send_template_message(
        WhatsappMessage(
            to="5217779313704",
            template=_team_invite_template("Refacciones García", invite_id),
        )
    )
    assert result["template_name"] == "eassymo_team_invite"
    assert result["message_sid"] == "wamid.TEAM"
    template = mock_post.call_args.kwargs["json"]["template"]
    assert template["name"] == "eassymo_team_invite"
    assert template["language"]["code"] == "es_MX"
    assert template["components"][0]["type"] == "body"
    assert template["components"][0]["parameters"] == [
        {"type": "text", "text": "Refacciones García"}
    ]
    assert template["components"][1]["type"] == "button"
    assert template["components"][1]["sub_type"] == "url"
    button_text = template["components"][1]["parameters"][0]["text"]
    assert button_text == invite_id
    assert "https://" not in button_text


@patch("app.services.WhatsappService.requests.post")
def test_send_network_invite_template_variable_order(mock_post, monkeypatch):
    mock_post.return_value = _graph_ok("wamid.NET")
    service = _cloud_service(monkeypatch)
    census_id = "65fca0b3cee797816ade67f7"
    result = service.send_template_message(
        WhatsappMessage(
            to="5217779313704",
            template=_network_invite_template(
                "Refacciones Pedro",
                "Refacciones García",
                "2",
                census_id,
            ),
        )
    )
    assert result["success"] is True
    template = mock_post.call_args.kwargs["json"]["template"]
    assert template["name"] == "eassymo_provider_invite"
    assert template["language"]["code"] == "es_MX"
    body_params = template["components"][0]["parameters"]
    assert [item["text"] for item in body_params] == [
        "Refacciones Pedro",
        "Refacciones García",
        "2",
    ]
    assert template["components"][1]["parameters"][0]["text"] == census_id


@patch("app.services.WhatsappService.requests.post")
def test_delivery_invite_freeform_when_template_unset(mock_post, monkeypatch):
    monkeypatch.delenv("WHATSAPP_TEMPLATE_DELIVERY_INVITE", raising=False)
    mock_post.return_value = _graph_ok("wamid.DEL")
    service = _cloud_service(monkeypatch)
    result = service.send_delivery_invite(
        "5216140000000",
        "Carlos",
        "https://eassymo.mx/delivery-invite/tok",
    )
    assert result["success"] is True
    assert result["message_sid"] == "wamid.DEL"
    assert result["status"] == "sent"
    assert set(result) == {"success", "message_sid", "status"}
    payload = mock_post.call_args.kwargs["json"]
    assert payload["type"] == "text"
    expected = DELIVERY_INVITE_FREEFORM.format(
        guest_name="Carlos",
        invite_url="https://eassymo.mx/delivery-invite/tok",
    )
    assert payload["text"]["body"] == expected
    assert "tienes una entrega asignada en Eassymo" in payload["text"]["body"]
    assert payload.get("template") is None
    assert "eassymo_courier_invite" not in json.dumps(payload)


@patch("app.services.WhatsappService.inbound_repo")
def test_check_message_status_reads_stored_webhook_status(mock_repo, monkeypatch):
    mock_repo.find_by_message_sid.return_value = {
        "message_sid": "wamid.OUT1",
        "status": "delivered",
        "from_number": "5217779313704",
        "to_number": "5216141115669",
        "created_at": "2026-09-30T00:00:00+00:00",
        "updated_at": "2026-09-30T00:01:00+00:00",
    }
    service = _cloud_service(monkeypatch)
    result = service.check_message_status("wamid.OUT1")
    assert result["status"] == "delivered"
    assert result["message_sid"] == "wamid.OUT1"
    assert result["to"] == "5217779313704"


@patch("app.services.WhatsappService.inbound_repo")
def test_check_message_status_404_when_unknown(mock_repo, monkeypatch):
    mock_repo.find_by_message_sid.return_value = None
    service = _cloud_service(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        service.check_message_status("wamid.MISSING")
    assert exc.value.status_code == 404
