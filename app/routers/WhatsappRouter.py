from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Path, Request, status
from fastapi.responses import JSONResponse, Response

from app.schemas.WhatasppMessage import WhatsappMessage
from app.services import WhatsappService as whatsAppService
from app.services.WhatsappInboundService import WhatsappInboundService
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
import logging

logger = logging.getLogger(__name__)

whatsAppRouter = APIRouter(prefix="/whatsAppMessage")

whatsapp_service = whatsAppService.WhatsappService()
inbound_service = WhatsappInboundService()


@whatsAppRouter.post("/inbound", tags=["WhatsApp"])
async def inbound_whatsapp_webhook(
    request: Request, background_tasks: BackgroundTasks
):
    """
    Twilio inbound webhook for WhatsApp messages sent to Eassymo's sender number.
    Configure in Twilio Console → Messaging Service / WhatsApp sender → When a message comes in.
    """
    form = await request.form()
    twiml, payload, created = inbound_service.handle_inbound(request, form)
    if created:
        if inbound_service.extract_enabled:
            background_tasks.add_task(inbound_service.process_intake, payload, created)
        else:
            background_tasks.add_task(inbound_service.maybe_send_ack, payload, created)
    return Response(content=twiml, media_type="application/xml")


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
