from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from fastapi import HTTPException
from app.schemas.WhatasppMessage import WhatsappMessage
import os
from dotenv import load_dotenv
from typing import Dict, Any, Optional
import logging
import json

import requests

load_dotenv()

logger = logging.getLogger(__name__)


class WhatsappService:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
        self.cloud_token = os.getenv("WHATSAPP_CLOUD_TOKEN", "").strip()
        self.cloud_phone_number_id = os.getenv(
            "WHATSAPP_CLOUD_PHONE_NUMBER_ID", ""
        ).strip()
        self.cloud_api_version = os.getenv("WHATSAPP_CLOUD_API_VERSION", "v21.0").strip()
        self.client = None

        if self.account_sid and self.auth_token:
            self.client = Client(self.account_sid, self.auth_token)
        else:
            logger.warning(
                "Twilio credentials not configured; WhatsApp features are disabled"
            )

    def _get_client(self) -> Client:
        if self.client is None:
            raise HTTPException(
                status_code=503,
                detail="Twilio is not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.",
            )
        return self.client

    def send_template_message(self, message: WhatsappMessage) -> Dict[str, Any]:
        try:
            content_variables = {
                str(i + 1): str(value)
                for i, value in enumerate(message.template.variables)
            }


            response = self._get_client().messages.create(
                from_=f"whatsapp:{self.from_number}",
                to=f"whatsapp:{message.to}",
                content_sid=message.template.name,
                content_variables=json.dumps(content_variables),
            )

            logger.info("WhatsApp template sent. SID=%s template=%s", response.sid, message.template.name)

            return {
                "success": True,
                "message_sid": response.sid,
                "status": response.status,
                "to": message.to,
                "template_name": message.template.name,
            }
        except TwilioRestException as e:
            logger.error(
                "Twilio template send failed code=%s template=%s to=%s: %s",
                e.code,
                message.template.name,
                message.to,
                e.msg,
            )
            detail = f"Failed to send WhatsApp template (Twilio {e.code}: {e.msg})"
            if e.code in (21655, 92006):
                detail += (
                    ". Verify TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN are LIVE credentials "
                    "for the account that owns this Content SID, not Test Credentials."
                )
            raise HTTPException(status_code=500, detail=detail)
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected error while sending message"
            )

    def send_delivery_invite(self, guest_phone: str, guest_name: str, invite_url: str) -> Dict[str, Any]:
        """
        Sends the delivery invite WhatsApp message to a guest phone number.
        Uses the Content Template if TWILIO_DELIVERY_INVITE_TEMPLATE_SID is configured,
        otherwise falls back to a freeform message (works within 24 h conversation window).
        """
        template_sid = os.getenv("TWILIO_DELIVERY_INVITE_TEMPLATE_SID")

        try:
            if template_sid:
                response = self._get_client().messages.create(
                    from_=f"whatsapp:{self.from_number}",
                    to=f"whatsapp:{guest_phone}",
                    content_sid=template_sid,
                    content_variables=json.dumps({"1": guest_name, "2": invite_url}),
                )
            else:
                freeform_body = (
                    f"Hola {guest_name}, tienes una entrega asignada en Eassymo 🚚\n"
                    f"Toca el enlace para ver los detalles y confirmar tu entrega:\n{invite_url}"
                )
                response = self._get_client().messages.create(
                    from_=f"whatsapp:{self.from_number}",
                    to=f"whatsapp:{guest_phone}",
                    body=freeform_body,
                )

            return {
                "success": True,
                "message_sid": response.sid,
                "status": response.status,
            }
        except TwilioRestException as e:
            logger.error(f"Twilio delivery invite error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to send delivery invite WhatsApp message",
            )
        except Exception as e:
            logger.error(f"Unexpected error sending delivery invite: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Unexpected error while sending delivery invite",
            )

    def send_text_message(self, to: str, body: str) -> Dict[str, Any]:
        """Send a freeform WhatsApp message (requires an open 24h session window)."""
        try:
            response = self._get_client().messages.create(
                from_=f"whatsapp:{self.from_number}",
                to=f"whatsapp:{to}",
                body=body,
            )
            return {
                "success": True,
                "message_sid": response.sid,
                "status": response.status,
                "to": to,
            }
        except TwilioRestException as e:
            logger.error(f"Twilio text message error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to send WhatsApp text message",
            )
        except Exception as e:
            logger.error(f"Unexpected error sending text message: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Unexpected error while sending WhatsApp text message",
            )

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
        to_digits = "".join(ch for ch in (to or "") if ch.isdigit() or ch == "+")
        url = (
            f"https://graph.facebook.com/{self.cloud_api_version}/"
            f"{self.cloud_phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_digits,
            "type": "reaction",
            "reaction": {
                "message_id": whatsapp_message_id,
                "emoji": emoji,
            },
        }
        headers = {
            "Authorization": f"Bearer {self.cloud_token}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
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
        try:
            message = self._get_client().messages(message_sid).fetch()
            
            return {
                "message_sid": message_sid,
                "status": message.status,
                "error_code": message.error_code,
                "error_message": message.error_message,
                "date_sent": str(message.date_sent),
                "date_updated": str(message.date_updated),
                "to": message.to,
                "from": message.from_
            }

        except TwilioRestException as e:
            logger.error(f"Error checking message status: {str(e)}")
            raise HTTPException(
                status_code=404 if e.code == 20404 else 500,
                detail=f"Error checking message status: {str(e)}"
            )
