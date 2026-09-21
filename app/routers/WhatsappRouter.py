from fastapi.responses import JSONResponse, Response
from fastapi import APIRouter, Body, status, HTTPException, Path, Request
from app.schemas.WhatasppMessage import WhatsappMessage
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.services import WhatsappService as whatsAppService
from app.services.WhatsappInboundService import WhatsappInboundService
import logging

logger = logging.getLogger(__name__)

whatsAppRouter = APIRouter(prefix="/whatsAppMessage")

whatsapp_service = whatsAppService.WhatsappService()
inbound_service = WhatsappInboundService()


@whatsAppRouter.post("/inbound", tags=["WhatsApp"])
async def inbound_whatsapp(request: Request):
    form = await request.form()
    try:
        twiml, payload, created = inbound_service.handle_inbound(request, form)
    except HTTPException as exc:
        logger.error("Inbound WhatsApp webhook rejected: %s", exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=get_unsuccessful_response(exc),
        )
    inbound_service.maybe_send_ack(payload, created)
    inbound_service.process_intake(payload, created)
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
