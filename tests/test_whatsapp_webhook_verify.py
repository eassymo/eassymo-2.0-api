import pytest
from fastapi import HTTPException

from app.services.WhatsappInboundService import WhatsappInboundService


def test_verify_subscription_returns_challenge(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "eassymo-verify")
    challenge = WhatsappInboundService().verify_subscription(
        "subscribe", "eassymo-verify", "1158201444"
    )
    assert challenge == "1158201444"


def test_verify_subscription_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "eassymo-verify")
    with pytest.raises(HTTPException) as exc:
        WhatsappInboundService().verify_subscription(
            "subscribe", "other-token", "1158201444"
        )
    assert exc.value.status_code == 403


def test_verify_subscription_requires_configured_token(monkeypatch):
    monkeypatch.delenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        WhatsappInboundService().verify_subscription("subscribe", "eassymo-verify", "1")
    assert exc.value.status_code == 503
