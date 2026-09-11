from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from fastapi import HTTPException
from app.schemas.WhatasppMessage import WhatsappMessage
import os
from dotenv import load_dotenv
from typing import Dict, Any
import logging
import json

load_dotenv()

logger = logging.getLogger(__name__)


class WhatsappService:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
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
