from fastapi import APIRouter, Body, status, Query
from app.schemas.Chat import Chat
from app.schemas.Message import Message
from app.services import ChatService as chatService
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

chatRouter = APIRouter(prefix="/chat")


@chatRouter.post("", response_description="", tags=["Chat"])
def insert(chat: Chat = Body(...)):
    try:
        response = chatService.insert(chat)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@chatRouter.post("/send-message/{chatId}", response_description="Boolean that confirms message is stored", tags=["Chat"])
def send_message(message: Message = Body(...)):
    try:
        response = chatService.add_message(message)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@chatRouter.get("/find-by-request-or-order-id", response_description="chat found based on the request or order id", tags=["Chat"])
def find_by_request_or_order_id(id: str = Query(None, title="id"), type: str = Query(None, title="type")):
    try:
        response = chatService.find_by_request_or_order_id(id, type)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@chatRouter.get('/to-be-read/{id}', response_description="Integer number of the messages that still need to be read", tags=["Chat"])
def to_be_read(id: str, type: str = Query(None, title="type"), userUid: str = Query(None, title="userUid")):
    try:
        response = chatService.to_be_read(id, userUid, type)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@chatRouter.post('/read-messages', response_description="Boolean that will indicate if messages where read for a certain user")
def read_messages(id: str = Query(None, title="order or request id"), user_uid: str = Query(None, title="user_uid"), type: str = Query(None, title="type")):
    try:
        response = chatService.read_messages(id, user_uid, type)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
