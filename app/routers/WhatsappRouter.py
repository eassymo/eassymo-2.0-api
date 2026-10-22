from fastapi.responses import JSONResponse, Response
from fastapi import APIRouter, Body, Query, status, HTTPException, Path, Request
from app.schemas.WhatasppMessage import WhatsappMessage
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.services import WhatsappService as whatsAppService
from app.services.WhatsappInboundService import WhatsappInboundService
import logging

logger = logging.getLogger(__name__)

whatsAppRouter = APIRouter(prefix="/whatsAppMessage")

whatsapp_service = whatsAppService.WhatsappService()
inbound_service = WhatsappInboundService()


@whatsAppRouter.get("/inbound", tags=["WhatsApp"])
def verify_whatsapp_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    challenge = inbound_service.verify_subscription(
        hub_mode, hub_verify_token, hub_challenge
    )
    return Response(content=challenge, media_type="text/plain")


@whatsAppRouter.post("/inbound", tags=["WhatsApp"])
async def inbound_whatsapp(request: Request):
    raw_body = await request.body()
    try:
        items = inbound_service.handle_inbound(request, raw_body)
    except HTTPException as exc:
        logger.error("Inbound WhatsApp webhook rejected: %s", exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=get_unsuccessful_response(exc),
        )
    for payload, created in items:
        inbound_service.maybe_send_ack(payload, created)
        inbound_service.process_intake(payload, created)
    return JSONResponse(content={}, status_code=status.HTTP_200_OK)


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
