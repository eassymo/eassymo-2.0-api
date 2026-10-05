from fastapi import APIRouter, Body, Request, status, Query, Header
from app.schemas.Chat import Chat
from app.schemas.Message import Message
from app.services import ChatService as chatService
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.dependencies.group_auth import assert_group_membership, require_authenticated_uid
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response, error_json_response

chatRouter = APIRouter(prefix="/chat")


@chatRouter.post("", response_description="", tags=["Chat"])
def insert(chat: Chat = Body(...)):
    try:
        response = chatService.insert(chat)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return error_json_response(e)


@chatRouter.post("/send-message/{chatId}", response_description="Boolean that confirms message is stored", tags=["Chat"])
def send_message(request: Request, message: Message = Body(...), groupselected: str = Header(None)):
    try:
        caller_uid = require_authenticated_uid(request)
        assert_group_membership(caller_uid, str(groupselected))
        response = chatService.add_message(message, caller_uid, groupselected)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return error_json_response(e)


@chatRouter.post("/realtime-access", response_description="Grant RTDB ACL for chat events", tags=["Chat"])
def realtime_access(request: Request, body=Body(...), groupselected: str = Header(None)):
    try:
        caller_uid = require_authenticated_uid(request)
        assert_group_membership(caller_uid, str(groupselected))
        entity_id = body.get("id")
        entity_type = body.get("type")
        if not entity_id or not entity_type:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response("id and type are required"),
            )
        granted = chatService.grant_realtime_access(entity_id, entity_type, caller_uid, groupselected)
        if not granted:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=get_unsuccessful_response("Failed to grant realtime chat access"),
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder({"granted": granted})),
        )
    except Exception as e:
        return error_json_response(e)


@chatRouter.get("/find-by-request-or-order-id", response_description="chat found based on the request or order id", tags=["Chat"])
def find_by_request_or_order_id(
    request: Request,
    id: str = Query(None, title="id"),
    type: str = Query(None, title="type"),
    groupselected: str = Header(None),
):
    try:
        caller_uid = require_authenticated_uid(request)
        assert_group_membership(caller_uid, str(groupselected))
        if type == "request":
            chatService._assert_chat_entity_access(id, "request", str(groupselected))
        elif type == "order":
            chatService._assert_chat_entity_access(id, "order", str(groupselected))
        response = chatService.find_by_request_or_order_id(
            id,
            type,
            viewer_group_id=str(groupselected),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return error_json_response(e)


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
        return error_json_response(e)


@chatRouter.post('/read-messages', response_description="Boolean that will indicate if messages where read for a certain user")
def read_messages(request: Request, id: str = Query(None, title="order or request id"), user_uid: str = Query(None, title="user_uid"), type: str = Query(None, title="type"), groupselected: str = Header(None)):
    try:
        caller_uid = require_authenticated_uid(request)
        assert_group_membership(caller_uid, str(groupselected))
        response = chatService.read_messages(id, caller_uid, type, groupselected)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(jsonable_encoder(response)))
    except Exception as e:
        return error_json_response(e)
