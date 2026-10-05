from fastapi import HTTPException
from app.schemas.WhatasppMessage import WhatsappMessage, WhatsappTemplate
import os
from dotenv import load_dotenv
from typing import Any, Dict, List, Optional
import logging

import requests

from app.repositories import WhatsappInboundRepository as inbound_repo

load_dotenv()

logger = logging.getLogger(__name__)

DELIVERY_INVITE_FREEFORM = (
    "Hola {guest_name}, tienes una entrega asignada en Eassymo 🚚\n"
    "Toca el enlace para ver los detalles y confirmar tu entrega:\n{invite_url}"
)


class WhatsappService:
    def __init__(self):
        self.cloud_token = os.getenv("WHATSAPP_CLOUD_TOKEN", "").strip()
        self.cloud_phone_number_id = os.getenv(
            "WHATSAPP_CLOUD_PHONE_NUMBER_ID", ""
        ).strip()
        self.cloud_api_version = os.getenv("WHATSAPP_CLOUD_API_VERSION", "v21.0").strip()
        self.template_language = os.getenv(
            "WHATSAPP_TEMPLATE_LANGUAGE", "es_MX"
        ).strip() or "es_MX"
        if not self.cloud_token or not self.cloud_phone_number_id:
            logger.warning(
                "WhatsApp Cloud API credentials not configured; WhatsApp features are disabled"
            )

    def _require_cloud(self) -> None:
        if not self.cloud_token or not self.cloud_phone_number_id:
            raise HTTPException(
                status_code=503,
                detail=(
                    "WhatsApp Cloud API is not configured. "
                    "Set WHATSAPP_CLOUD_TOKEN and WHATSAPP_CLOUD_PHONE_NUMBER_ID."
                ),
            )

    def _messages_url(self) -> str:
        return (
            f"https://graph.facebook.com/{self.cloud_api_version}/"
            f"{self.cloud_phone_number_id}/messages"
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cloud_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _recipient(to: str) -> str:
        return "".join(ch for ch in (to or "") if ch.isdigit())

    def _post_cloud_message(
        self,
        payload: Dict[str, Any],
        *,
        failure_detail: str,
    ) -> Dict[str, Any]:
        self._require_cloud()
        try:
            response = requests.post(
                self._messages_url(),
                headers=self._headers(),
                json=payload,
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.error("WhatsApp Cloud API request failed: %s", exc)
            raise HTTPException(status_code=500, detail=failure_detail)

        if response.status_code >= 400:
            logger.error(
                "WhatsApp Cloud API send failed status=%s body=%s",
                response.status_code,
                response.text[:300],
            )
            detail = failure_detail
            try:
                error = (response.json() or {}).get("error") or {}
                meta = error.get("error_user_msg") or error.get("message")
                if meta:
                    detail = f"{failure_detail}: {meta}"
            except ValueError:
                pass
            raise HTTPException(status_code=500, detail=detail)

        try:
            data = response.json()
        except ValueError:
            logger.error("WhatsApp Cloud API returned non-JSON body")
            raise HTTPException(status_code=500, detail=failure_detail)

        messages = data.get("messages") or []
        first = messages[0] if messages else {}
        message_id = (first or {}).get("id")
        if not message_id:
            logger.error("WhatsApp Cloud API response missing message id: %s", data)
            raise HTTPException(status_code=500, detail=failure_detail)
        return {
            "success": True,
            "message_sid": message_id,
            "status": (first or {}).get("message_status") or "sent",
            "to": payload.get("to"),
        }

    @staticmethod
    def _template_components(variables: List[str]) -> List[Dict[str, Any]]:
        values = [str(value) for value in variables]
        if not values:
            return []
        if len(values) == 1:
            return [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": values[0]}],
                }
            ]
        body_params = [{"type": "text", "text": value} for value in values[:-1]]
        return [
            {"type": "body", "parameters": body_params},
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": values[-1]}],
            },
        ]

    def send_template_message(self, message: WhatsappMessage) -> Dict[str, Any]:
        template_name = (message.template.name or "").strip()
        if not template_name:
            raise HTTPException(
                status_code=503,
                detail="WhatsApp template name is not configured",
            )
        language = (
            (message.template.language or "").strip()
            or self.template_language
        )
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._recipient(message.to),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }
        components = self._template_components(message.template.variables)
        if components:
            payload["template"]["components"] = components

        result = self._post_cloud_message(
            payload,
            failure_detail=f"Failed to send WhatsApp template {template_name}",
        )
        logger.info(
            "WhatsApp template sent. SID=%s template=%s",
            result["message_sid"],
            template_name,
        )
        result["template_name"] = template_name
        result["to"] = message.to
        return result

    def send_delivery_invite(
        self, guest_phone: str, guest_name: str, invite_url: str
    ) -> Dict[str, Any]:
        """
        Sends the delivery invite WhatsApp message to a guest phone number.
        Uses the Cloud API template if WHATSAPP_TEMPLATE_DELIVERY_INVITE is set,
        otherwise falls back to a freeform message (works within 24 h conversation window).
        """
        template_name = os.getenv("WHATSAPP_TEMPLATE_DELIVERY_INVITE", "").strip()

        try:
            if template_name:
                result = self.send_template_message(
                    WhatsappMessage(
                        to=guest_phone,
                        template=WhatsappTemplate(
                            name=template_name,
                            variables=[guest_name, invite_url],
                        ),
                    )
                )
            else:
                freeform_body = DELIVERY_INVITE_FREEFORM.format(
                    guest_name=guest_name,
                    invite_url=invite_url,
                )
                result = self.send_text_message(guest_phone, freeform_body)
            return {
                "success": True,
                "message_sid": result["message_sid"],
                "status": result.get("status"),
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Unexpected error sending delivery invite: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Unexpected error while sending delivery invite",
            )

    def _media_is_ready(self, media_url: str) -> bool:
        """Fetch the card once so Meta receives a cached PNG, not an error page."""
        try:
            response = requests.get(
                media_url,
                timeout=20,
                headers={
                    "Accept": "image/png",
                    "User-Agent": "EassymoDraftCard/1.0",
                },
            )
        except requests.RequestException as exc:
            logger.warning("Draft card image fetch failed for %s: %s", media_url, exc)
            return False

        content_type = (response.headers.get("content-type") or "").lower()
        body = response.content or b""
        if (
            response.status_code != 200
            or not content_type.startswith("image/")
            or not body.startswith(b"\x89PNG")
            or len(body) < 500
        ):
            logger.warning(
                "Draft card image not usable status=%s type=%s bytes=%s url=%s",
                response.status_code,
                content_type,
                len(body),
                media_url,
            )
            return False
        return True

    def send_text_message(
        self,
        to: str,
        body: str,
        media_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a freeform WhatsApp message (requires an open 24h session window)."""
        image_url = media_url if media_url and self._media_is_ready(media_url) else None
        if media_url and not image_url:
            logger.warning(
                "Sending draft text without image because the card PNG was not ready"
            )
        try:
            return self._create_session_message(to, body, image_url)
        except HTTPException:
            if not image_url:
                raise
            logger.warning("WhatsApp image send failed for %s; sending the link as text", to)
            return self._create_session_message(to, body, None)

    def _create_session_message(
        self,
        to: str,
        body: str,
        media_url: Optional[str],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._recipient(to),
        }
        if media_url:
            payload["type"] = "image"
            payload["image"] = {"link": media_url, "caption": body}
        else:
            payload["type"] = "text"
            payload["text"] = {"body": body, "preview_url": True}

        result = self._post_cloud_message(
            payload,
            failure_detail="Failed to send WhatsApp text message",
        )
        result["to"] = to
        return result

    @property
    def native_reactions_enabled(self) -> bool:
        return bool(self.cloud_token and self.cloud_phone_number_id)

    def react_to_message(
        self,
        to: str,
        whatsapp_message_id: str,
        emoji: str = "🔗",
    ) -> Dict[str, Any]:
        """Apply a native WhatsApp reaction via Meta Cloud API when configured."""
        if not self.native_reactions_enabled or not whatsapp_message_id:
            return {"success": False, "method": "native", "reason": "not_configured"}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._recipient(to),
            "type": "reaction",
            "reaction": {
                "message_id": whatsapp_message_id,
                "emoji": emoji,
            },
        }
        try:
            response = requests.post(
                self._messages_url(),
                headers=self._headers(),
                json=payload,
                timeout=15,
            )
            if response.status_code >= 400:
                logger.warning(
                    "Meta reaction failed status=%s body=%s",
                    response.status_code,
                    response.text[:300],
                )
                return {
                    "success": False,
                    "method": "native",
                    "reason": response.text[:200],
                }
            return {"success": True, "method": "native"}
        except requests.RequestException as exc:
            logger.warning("Meta reaction request failed: %s", exc)
            return {"success": False, "method": "native", "reason": str(exc)}

    def send_link_fallback(self, to: str, folio_code: str) -> Dict[str, Any]:
        body = f"🔗 - {folio_code} vinculado"
        return self.send_text_message(to, body)

    def check_message_status(self, message_sid: str) -> Dict[str, Any]:
        doc = inbound_repo.find_by_message_sid(message_sid)
        if not doc:
            raise HTTPException(
                status_code=404,
                detail="Error checking message status: message not found",
            )
        return {
            "message_sid": message_sid,
            "status": doc.get("status"),
            "error_code": doc.get("error_code"),
            "error_message": doc.get("error_message"),
            "date_sent": str(doc.get("created_at") or ""),
            "date_updated": str(doc.get("updated_at") or ""),
            "to": doc.get("from_number"),
            "from": doc.get("to_number"),
        }
