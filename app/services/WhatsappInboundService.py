import logging
import os
from typing import Any, Dict, Mapping, Optional, Tuple

from fastapi import HTTPException, Request
from twilio.request_validator import RequestValidator

from app.repositories import WhatsappInboundRepository as inbound_repo
from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService
from app.services.WhatsappService import WhatsappService

logger = logging.getLogger(__name__)

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


class WhatsappInboundService:
    def __init__(self) -> None:
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.skip_signature = os.getenv(
            "WHATSAPP_WEBHOOK_SKIP_SIGNATURE", ""
        ).lower() in ("1", "true", "yes")
        self.auto_reply = os.getenv(
            "WHATSAPP_INBOUND_AUTO_REPLY", "true"
        ).lower() in ("1", "true", "yes")
        self.extract_enabled = os.getenv(
            "WHATSAPP_INTAKE_EXTRACT", "true"
        ).lower() in ("1", "true", "yes")
        self.whatsapp_service = WhatsappService()
        self.intake_processor = WhatsappIntakeProcessorService()

    def _public_webhook_url(self, request: Request) -> str:
        configured = os.getenv("TWILIO_WEBHOOK_PUBLIC_URL", "").strip()
        if configured:
            return configured.rstrip("/")

        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host") or request.headers.get(
            "host"
        )
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"
        return f"{proto}://{host}{path}"

    def validate_signature(
        self, request: Request, params: Mapping[str, str]
    ) -> None:
        if self.skip_signature:
            logger.warning(
                "WHATSAPP_WEBHOOK_SKIP_SIGNATURE enabled; skipping Twilio signature check"
            )
            return

        if not self.auth_token:
            raise HTTPException(
                status_code=503,
                detail="TWILIO_AUTH_TOKEN is not configured for webhook validation",
            )

        signature = request.headers.get("X-Twilio-Signature", "")
        if not signature:
            raise HTTPException(status_code=403, detail="Missing Twilio signature")

        url = self._public_webhook_url(request)
        validator = RequestValidator(self.auth_token)
        if not validator.validate(url, dict(params), signature):
            logger.warning("Invalid Twilio signature for inbound webhook url=%s", url)
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    @staticmethod
    def _strip_whatsapp_prefix(value: str) -> str:
        return value.removeprefix("whatsapp:").strip()

    def parse_form(self, form: Mapping[str, Any]) -> Dict[str, Any]:
        num_media = int(form.get("NumMedia") or 0)
        media_urls = [
            str(form.get(f"MediaUrl{i}") or "")
            for i in range(num_media)
            if form.get(f"MediaUrl{i}")
        ]

        return {
            "message_sid": str(form.get("MessageSid") or ""),
            "account_sid": str(form.get("AccountSid") or ""),
            "from_number": self._strip_whatsapp_prefix(str(form.get("From") or "")),
            "to_number": self._strip_whatsapp_prefix(str(form.get("To") or "")),
            "body": str(form.get("Body") or ""),
            "num_media": num_media,
            "media_urls": media_urls,
            "profile_name": str(form.get("ProfileName") or ""),
            "wa_id": str(form.get("WaId") or ""),
            "forwarded": str(form.get("Forwarded") or "").lower() == "true",
            "status": "received",
        }

    def persist_inbound(self, payload: Dict[str, Any]) -> Tuple[Optional[str], bool]:
        if not payload.get("message_sid"):
            raise HTTPException(status_code=400, detail="Missing MessageSid")

        doc_id, created = inbound_repo.insert_if_new(payload)
        if created:
            logger.info(
                "Stored inbound WhatsApp message_sid=%s from=%s",
                payload["message_sid"],
                payload.get("from_number"),
            )
        else:
            logger.info(
                "Duplicate inbound WhatsApp message_sid=%s ignored",
                payload["message_sid"],
            )
        return doc_id, created

    def maybe_send_ack(self, payload: Dict[str, Any], created: bool) -> None:
        if not created:
            return
        if self.extract_enabled:
            return
        if not self.auto_reply:
            return

        to_number = payload.get("from_number")
        if not to_number:
            return

        body = payload.get("body") or ""
        preview = body.strip()
        if len(preview) > 80:
            preview = f"{preview[:77]}..."

        if preview:
            message = (
                "Recibido en Eassymo. Estamos procesando tu mensaje:\n"
                f"“{preview}”"
            )
        else:
            message = (
                "Recibido en Eassymo. Estamos procesando tu mensaje "
                "(texto o media pendiente de revisión)."
            )

        try:
            self.whatsapp_service.send_text_message(to_number, message)
        except HTTPException as exc:
            logger.error(
                "Failed to send inbound ack to %s: %s",
                to_number,
                exc.detail,
            )

    def process_intake(self, payload: Dict[str, Any], created: bool) -> None:
        if not created or not self.extract_enabled:
            return
        try:
            self.intake_processor.process_inbound(payload)
        except Exception as exc:
            logger.exception("WhatsApp intake processing failed: %s", exc)

    def handle_inbound(
        self, request: Request, form: Mapping[str, Any]
    ) -> Tuple[str, Dict[str, Any], bool]:
        params = {key: str(value) for key, value in form.items()}
        self.validate_signature(request, params)

        payload = self.parse_form(form)
        doc_id, created = self.persist_inbound(payload)
        payload["mongo_id"] = doc_id

        return EMPTY_TWIML, payload, created
