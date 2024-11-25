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

        self.client = Client(self.account_sid, self.auth_token)

    def send_template_message(self, message: WhatsappMessage) -> Dict[str, Any]:
        try:
            content_variables = {
                str(i+1): str(value) 
                for i, value in enumerate(message.template.variables)
            }

            print(self)

            response = self.client.messages.create(
                from_=f"whatsapp:{self.from_number}",
                to=f"whatsapp:{message.to}",
                content_sid=message.template.name,
                content_variables=json.dumps(content_variables)
            )

            print(f"Message sent successfully. SID: {response.sid}")

            return {
                "success": True,
                "message_sid": response.sid,
                "status": response.status,
                "to": message.to,
                "template_name": message.template.name
            }
        except TwilioRestException as e:
            logger.error(f"Twilio error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to send Whatsapp template"
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected error while sending message"
            )

    def check_message_status(self, message_sid: str) -> Dict[str, Any]:
        try:
            message = self.client.messages(message_sid).fetch()
            
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
