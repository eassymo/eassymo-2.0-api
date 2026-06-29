from app.repositories import ChatRepository as chatRepository
from app.schemas.Chat import Chat
from app.schemas.Message import Message
from typing import List, Dict, Any, Optional
from pymongo.errors import PyMongoError
from fastapi import HTTPException, status
from bson import ObjectId


def _user_group_read_key(user_uid: str, group_id: Optional[str]) -> str:
    """Stable key for usersThatRead; group_id must be present (from header or chat)."""
    if not user_uid or not str(user_uid).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_uid is required to mark or count read messages",
        )
    if not group_id or not str(group_id).strip() or str(group_id).strip().lower() == "none":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="groupselected header is required for chat read state",
        )
    return f"{str(user_uid).strip()}-{str(group_id).strip()}"


def _legacy_none_group_read_key(group_id: str) -> str:
    return f"None-{str(group_id).strip()}"


def _message_is_unread_for_user(msg: Dict[str, Any], user_group_key: str, group_id: str) -> bool:
    users_that_read = msg.get("usersThatRead") or {}
    if users_that_read.get(user_group_key) is True:
        return False
    # Legacy rows written when GroupSelected header was missing on read-messages
    if users_that_read.get(_legacy_none_group_read_key(group_id)) is True:
        return False
    return True


def _mark_message_read_for_user(message: Message, user_group_key: str, group_id: str) -> None:
    users_that_read = dict(message.usersThatRead or {})
    users_that_read.pop(_legacy_none_group_read_key(group_id), None)
    users_that_read[user_group_key] = True
    message.usersThatRead = users_that_read
    message.isRead = True


def insert(chat: Chat):
    try:
        chat_json = chat.toJson()
        chat_json.pop("_id")
        inserted_chat = chatRepository.insert(chat_json)
        inserted_chat_id = inserted_chat.inserted_id

        found_chat = chatRepository.find_by_id(inserted_chat_id)

        if found_chat is not None:
            return Chat(**found_chat).toJson()
        else:
            raise HTTPException(
                status_code=404, detail="Chat not found after insertion")

    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting chat {err}')


def find_by_request_or_order_id(request_order_id: str, type: str):
    try:

        chat_data: any = None
        chat: Chat | None = None

        if type == "request":
            aggregation_result = list(
                chatRepository.find_by_request_id(request_order_id))
            if len(aggregation_result) > 0:
                chat_data = aggregation_result[0]
        elif type == "order":
            aggregation_result = list(
                chatRepository.find_by_order_id(request_order_id))
            if len(aggregation_result) > 0:
                chat_data = aggregation_result[0]

        if chat_data is not None:
            chat = Chat(**chat_data)

        return chat.toJson() if chat is not None else None

    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding chat {err}')


def to_be_read_v2(ids: List[str], group_id: str, user_uid: str, type = 'request') -> dict:
    """Unread counts per request/order id; source of truth is usersThatRead, not isRead."""
    try:
        result = {id: 0 for id in ids}

        if type is None:
            type = 'request'
        
        chats = []
        if type == 'request':
            chats = list(chatRepository.find_by_request_ids(ids))

        if type == 'order':
            chats = list(chatRepository.find_by_order_ids(ids))

        id_field = "orderId" if type == "order" else "requestId"
        user_group_key = _user_group_read_key(user_uid, group_id)

        for chat in chats:
            request_id = chat.get(id_field)
            if request_id not in result:
                continue
            messages = chat.get("messages") or []

            result[request_id] = sum(
                1 for msg in messages
                if _message_is_unread_for_user(msg, user_group_key, group_id)
            )
        return result
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding chat to be read messages {err}')


def read_messages(id: str, user_uid: str, type: str, group_selected: str):
    try:
        filters = {}

        if type == "request":
            filters = {"requestId": id}
        else:
            filters = {"orderId": id}

        chats_found = list(chatRepository.find(filters))
        if not chats_found:
            return True

        chat = Chat(**chats_found[0])

        resolved_group_id = group_selected or chat.groupId
        user_group_key = _user_group_read_key(user_uid, resolved_group_id)

        for message in chat.messages:
            _mark_message_read_for_user(message, user_group_key, resolved_group_id)

        chat_json = chat.toJson()
        chat_id = ObjectId(chat_json["_id"])
        chat_json.pop("_id")
        chatRepository.update_chat(chat_id, chat_json)

        return True
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while reading messages {err}')


def add_message(message: Message, user_uid: str, group_id: str):
    try:
        chat_id = ObjectId(message.chatId)

        chat_data = chatRepository.find_by_id(chat_id)
        chat = Chat(**chat_data)

        user_group_key = _user_group_read_key(user_uid, group_id)
        message.usersThatRead = {user_group_key: True}
        message.isRead = True

        chat.insert_message(message)

        chat_json = chat.toJson()

        chat_json.pop("_id")

        chatRepository.update_chat(chat_id, chat_json)

        return True
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting chat {err}')
