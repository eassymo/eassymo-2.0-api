from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, status, HTTPException, Path
from app.schemas.WhatasppMessage import WhatsappMessage
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.services import WhatsappService as whatsAppService
import logging

logger = logging.getLogger(__name__)

whatsAppRouter = APIRouter(prefix="/whatsAppMessage")

whatsapp_service = whatsAppService.WhatsappService()


@whatsAppRouter.post("/send_template", tags=["WhatsApp"])
def send_whatsapp_message(message: WhatsappMessage = Body(...)):
    try:
        response = whatsapp_service.send_template_message(message)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except HTTPException as e:
        logger.error(f"HTTP exception while sending template: {str(e)}")
        return JSONResponse(
            status_code=e.status_code,
            content=get_unsuccessful_response(e)
        )

@whatsAppRouter.get("/status/{message_sid}", tags=["WhatsApp"])
def check_message_status(
    message_sid: str = Path(..., description="The SID of the message to check")
):

    try:
        response = whatsapp_service.check_message_status(message_sid)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(response)
        )
    except HTTPException as e:
        logger.error(f"Error checking message status: {str(e)}")
        return JSONResponse(
            status_code=e.status_code,
            content=get_unsuccessful_response(e)
        )
