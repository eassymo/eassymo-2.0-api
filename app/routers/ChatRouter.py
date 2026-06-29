from fastapi import APIRouter, Body, Request, status, Query, Header
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
def send_message(request:Request, message: Message = Body(...), groupselected: str = Header(None)):
    try:

        user_info = request.state._state.get('user')

        response = chatService.add_message(message, user_info.get('uid'), groupselected)
        
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


@chatRouter.post('/to-be-read', response_description="Object with id of request and pending messages", tags=["Chat"])
def to_be_read(request:Request, body=Body(...), groupselected: str = Header(None)):
    try:
        ids = body.get("request_ids")

        user_info = request.state._state.get('user')

        type = body.get('type')

        if ids is None or len(ids) == 0:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=get_unsuccessful_response("Ids cannot be empty"))

        response = chatService.to_be_read_v2(ids, groupselected, user_info.get('uid'), type)

        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))


@chatRouter.post('/read-messages', response_description="Boolean that will indicate if messages where read for a certain user")
def read_messages(id: str = Query(None, title="order or request id"), user_uid: str = Query(None, title="user_uid"), type: str = Query(None, title="type"), groupselected: str = Header(None)):
    try:
        response = chatService.read_messages(id, user_uid, type, groupselected)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return JSONResponse(content=get_unsuccessful_response(e))
