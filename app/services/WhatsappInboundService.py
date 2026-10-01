import hashlib
import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from fastapi import HTTPException, Request

from app.repositories import WhatsappInboundRepository as inbound_repo
from app.services.WhatsappClarificationService import extract_whatsapp_message_id
from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService
from app.services.WhatsappService import WhatsappService

logger = logging.getLogger(__name__)

SKIP_MESSAGE_TYPES = frozenset({"reaction", "system", "unknown"})
MEDIA_TYPES = frozenset({"image", "video", "audio", "document", "sticker"})


class WhatsappInboundService:
    def __init__(self) -> None:
        self.app_secret = os.getenv("WHATSAPP_APP_SECRET", "").strip()
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

    def validate_signature(self, request: Request, raw_body: bytes) -> None:
        if self.skip_signature:
            logger.warning(
                "WHATSAPP_WEBHOOK_SKIP_SIGNATURE enabled; skipping Meta signature check"
            )
            return

        if not self.app_secret:
            raise HTTPException(
                status_code=503,
                detail="WHATSAPP_APP_SECRET is not configured for webhook validation",
            )

        header = request.headers.get("X-Hub-Signature-256") or request.headers.get(
            "x-hub-signature-256", ""
        )
        if not header:
            raise HTTPException(status_code=403, detail="Missing Meta signature")

        expected = "sha256=" + hmac.new(
            self.app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(header, expected):
            logger.warning("Invalid Meta signature for inbound webhook")
            raise HTTPException(status_code=403, detail="Invalid Meta signature")

    def verify_subscription(self, mode: str, token: str, challenge: str) -> str:
        """Meta calls this with a GET before it will save the callback URL."""
        expected = os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "").strip()
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="WHATSAPP_WEBHOOK_VERIFY_TOKEN is not configured",
            )
        token_ok = hmac.compare_digest(token or "", expected)
        if mode != "subscribe" or not token_ok or not (challenge or "").strip():
            raise HTTPException(status_code=403, detail="Webhook verification failed")
        return challenge

    @staticmethod
    def _strip_whatsapp_prefix(value: str) -> str:
        return value.removeprefix("whatsapp:").strip()

    @staticmethod
    def _message_body(message: Mapping[str, Any]) -> str:
        mtype = str(message.get("type") or "")
        if mtype == "text":
            return str((message.get("text") or {}).get("body") or "")
        if mtype in MEDIA_TYPES:
            media = message.get(mtype) or {}
            return str(media.get("caption") or "")
        if mtype == "interactive":
            interactive = message.get("interactive") or {}
            itype = interactive.get("type")
            if itype == "button_reply":
                return str((interactive.get("button_reply") or {}).get("title") or "")
            if itype == "list_reply":
                return str((interactive.get("list_reply") or {}).get("title") or "")
        if mtype == "button":
            return str((message.get("button") or {}).get("text") or "")
        return ""

    @staticmethod
    def _media_ids(message: Mapping[str, Any]) -> List[str]:
        mtype = str(message.get("type") or "")
        if mtype not in MEDIA_TYPES:
            return []
        media = message.get(mtype) or {}
        media_id = str(media.get("id") or "").strip()
        return [media_id] if media_id else []

    @staticmethod
    def _profile_name(message: Mapping[str, Any], value: Mapping[str, Any]) -> str:
        from_wa = str(message.get("from") or "")
        for contact in value.get("contacts") or []:
            if str(contact.get("wa_id") or "") == from_wa:
                return str((contact.get("profile") or {}).get("name") or "")
        contacts = value.get("contacts") or []
        if contacts:
            return str((contacts[0].get("profile") or {}).get("name") or "")
        return ""

    def parse_meta_message(
        self,
        message: Mapping[str, Any],
        value: Mapping[str, Any],
        *,
        account_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        mtype = str(message.get("type") or "")
        if mtype in SKIP_MESSAGE_TYPES:
            return None

        message_id = str(message.get("id") or "").strip()
        if not message_id:
            return None

        context = message.get("context") or {}
        forwarded = bool(
            context.get("forwarded") or context.get("frequently_forwarded")
        )
        replied_id = str(context.get("id") or "").strip()
        from_number = self._strip_whatsapp_prefix(str(message.get("from") or ""))
        metadata = value.get("metadata") or {}
        to_number = self._strip_whatsapp_prefix(
            str(metadata.get("display_phone_number") or "")
        )
        media_urls = self._media_ids(message)
        channel_metadata = json.dumps(message, ensure_ascii=False)

        return {
            "message_sid": message_id,
            "account_sid": account_id,
            "from_number": from_number,
            "to_number": to_number,
            "body": self._message_body(message),
            "num_media": len(media_urls),
            "media_urls": media_urls,
            "profile_name": self._profile_name(message, value),
            "wa_id": from_number,
            "forwarded": forwarded,
            "original_replied_message_sid": replied_id,
            "channel_metadata": channel_metadata,
            "whatsapp_message_id": message_id
            or extract_whatsapp_message_id(channel_metadata),
            "status": "received",
        }

    def extract_webhook_events(
        self, body: Mapping[str, Any]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        payloads: List[Dict[str, Any]] = []
        statuses: List[Dict[str, Any]] = []
        for entry in body.get("entry") or []:
            account_id = str(entry.get("id") or "")
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                for status_event in value.get("statuses") or []:
                    statuses.append(dict(status_event))
                for message in value.get("messages") or []:
                    parsed = self.parse_meta_message(
                        message, value, account_id=account_id
                    )
                    if parsed:
                        payloads.append(parsed)
        return payloads, statuses

    def apply_status_updates(self, statuses: List[Mapping[str, Any]]) -> None:
        for status_event in statuses:
            message_sid = str(status_event.get("id") or "").strip()
            if not message_sid:
                continue
            existing = inbound_repo.find_by_message_sid(message_sid)
            if not existing:
                continue
            fields: Dict[str, Any] = {"status": status_event.get("status")}
            errors = status_event.get("errors") or []
            if errors:
                first = errors[0] or {}
                fields["error_code"] = first.get("code")
                fields["error_message"] = first.get("title") or first.get("message")
            inbound_repo.update_fields(message_sid, fields)

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
            schedule = self.intake_processor.process_inbound(payload)
            if schedule and schedule.get("schedule_debounce"):
                thread = threading.Thread(
                    target=self.debounced_flush,
                    args=(
                        schedule["from_number"],
                        schedule["generation"],
                        schedule.get("flush_at"),
                    ),
                    daemon=True,
                )
                thread.start()
        except Exception as exc:
            logger.exception("WhatsApp intake processing failed: %s", exc)

    def debounced_flush(self, from_number: str, generation: int, flush_at) -> None:
        if flush_at is not None:
            if isinstance(flush_at, str):
                flush_at = datetime.fromisoformat(flush_at.replace("Z", "+00:00"))
            if isinstance(flush_at, datetime):
                if flush_at.tzinfo is None:
                    flush_at = flush_at.replace(tzinfo=timezone.utc)
                delay = (flush_at - datetime.now(timezone.utc)).total_seconds()
                if delay > 0:
                    time.sleep(delay)
        try:
            self.intake_processor.flush_if_ready(from_number, generation)
        except Exception as orig:
            logger.exception(
                "WhatsApp debounced flush failed for %s: %s", from_number, orig
            )

    def handle_inbound(
        self, request: Request, raw_body: bytes
    ) -> List[Tuple[Dict[str, Any], bool]]:
        self.validate_signature(request, raw_body)
        try:
            body = json.loads(raw_body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Invalid Meta webhook JSON: %s", exc)
            raise HTTPException(status_code=400, detail="Invalid webhook JSON")

        if not isinstance(body, dict):
            return []

        payloads, statuses = self.extract_webhook_events(body)
        self.apply_status_updates(statuses)

        results: List[Tuple[Dict[str, Any], bool]] = []
        for payload in payloads:
            doc_id, created = self.persist_inbound(payload)
            payload["mongo_id"] = doc_id
            results.append((payload, created))
        return results
