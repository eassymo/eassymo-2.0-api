import logging
from app.repositories import ChatRepository as chatRepository
from app.repositories import PartRequestRepository as partRequestRepository
from app.repositories import OrderRepository as orderRepository
from app.schemas.Chat import Chat
from app.schemas.Message import Message
from app.services import realtime_bus
from app.services.chat_display import mask_chat_for_viewer
from typing import List, Dict, Any, Optional, Literal
from pymongo.errors import PyMongoError
from fastapi import HTTPException, status
from bson import ObjectId

logger = logging.getLogger(__name__)

ChatEntityType = Literal["request", "order"]


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


def _group_can_access_part_request_doc(part_request: dict, group_id: str) -> bool:
    gid = str(group_id).strip()
    if gid == str(part_request.get("creatorGroup", "")):
        return True
    sellers = [str(s) for s in (part_request.get("subscribedSellers") or [])]
    if gid in sellers:
        return True
    followers = [str(f) for f in (part_request.get("subscribedFollowers") or [])]
    if gid in followers:
        return True
    return False


def _assert_chat_entity_access(entity_id: str, entity_type: str, group_id: str) -> None:
    if entity_type == "request":
        part_request = partRequestRepository.find_one_by_id(entity_id)
        if not part_request:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part request not found")
        if not _group_can_access_part_request_doc(part_request, group_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Group cannot access this chat")
        return

    if entity_type == "order":
        try:
            order_oid = ObjectId(entity_id)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid order id") from exc

        orders = list(orderRepository.find_by_id(order_oid))
        if not orders:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

        order = orders[0]
        part_request = order.get("part_request") or {}
        if _group_can_access_part_request_doc(part_request, group_id):
            return

        offer_group = (order.get("offer") or {}).get("group_id")
        if str(group_id) == str(offer_group):
            return

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Group cannot access this chat")

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid chat type")


def grant_realtime_access(
    entity_id: str,
    entity_type: ChatEntityType,
    user_uid: str,
    group_id: str,
) -> bool:
    _assert_chat_entity_access(entity_id, entity_type, group_id)
    participant_uids = _participant_uids_for_entity(
        entity_type,
        entity_id,
        extra_uids=[user_uid],
    )
    if not participant_uids:
        participant_uids = [user_uid]
    return realtime_bus.grant_chat_acl(entity_type, entity_id, participant_uids)


def _uids_from_group_ids(group_ids: List[str]) -> List[str]:
    clean_ids = [str(group_id).strip() for group_id in group_ids if group_id]
    if not clean_ids:
        return []
    try:
        from app.services import GroupService as groupService

        rows = groupService.find_users_by_groups_ids_v2(clean_ids)
    except Exception:
        logger.warning("Failed resolving chat participant uids for groups=%s", clean_ids, exc_info=True)
        return []

    uids: List[str] = []
    for row in rows or []:
        for uid in row.get("users") or []:
            if uid:
                uids.append(str(uid))
    return uids


def _participant_uids_for_entity(
    entity_type: ChatEntityType,
    entity_id: str,
    extra_uids: Optional[List[str]] = None,
) -> List[str]:
    uids = {str(uid) for uid in (extra_uids or []) if uid}

    try:
        if entity_type == "request":
            part_request = partRequestRepository.find_one_by_id(entity_id) or {}
            creator_user = part_request.get("creatorUser")
            if creator_user:
                uids.add(str(creator_user))
            group_ids = [
                part_request.get("creatorGroup"),
                *(part_request.get("subscribedSellers") or []),
                *(part_request.get("subscribedFollowers") or []),
            ]
            uids.update(_uids_from_group_ids(group_ids))
        elif entity_type == "order":
            try:
                order_oid = ObjectId(entity_id)
            except Exception:
                return list(uids)
            orders = list(orderRepository.find_by_id(order_oid))
            if not orders:
                return list(uids)
            order = orders[0]
            part_request = order.get("part_request") or {}
            creator_user = part_request.get("creatorUser")
            if creator_user:
                uids.add(str(creator_user))
            offer_group = (order.get("offer") or {}).get("group_id")
            group_ids = [
                part_request.get("creatorGroup"),
                *(part_request.get("subscribedSellers") or []),
                *(part_request.get("subscribedFollowers") or []),
                offer_group,
            ]
            uids.update(_uids_from_group_ids(group_ids))
    except Exception:
        logger.warning(
            "Failed resolving chat participants type=%s id=%s",
            entity_type,
            entity_id,
            exc_info=True,
        )

    return list(uids)


def _publish_message_event(chat: Chat, chat_id: ObjectId, message: Message) -> None:
    if chat.requestId:
        entity_type: ChatEntityType = "request"
        entity_id = str(chat.requestId)
    elif chat.orderId:
        entity_type = "order"
        entity_id = str(chat.orderId)
    else:
        return

    participant_uids = _participant_uids_for_entity(
        entity_type,
        entity_id,
        extra_uids=[message.senderId],
    )
    realtime_bus.grant_chat_acl(entity_type, entity_id, participant_uids)
    realtime_bus.publish_chat_event(
        entity_type,
        entity_id,
        {
            "chatId": str(chat_id),
            "message": message.toJson(),
        },
    )


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


def find_by_request_or_order_id(
    request_order_id: str,
    type: str,
    viewer_group_id: Optional[str] = None,
):
    try:

        chat_data: any = None
        chat: Chat | None = None
        creator_group_id: Optional[str] = None

        if type == "request":
            part_request = partRequestRepository.find_one_by_id(request_order_id)
            if part_request:
                creator_group_id = part_request.get("creatorGroup")
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

        if chat is None:
            return None

        chat_json = chat.toJson()
        entity_type: ChatEntityType = "request" if type == "request" else "order"
        return mask_chat_for_viewer(
            chat_json,
            entity_type=entity_type,
            creator_group_id=str(creator_group_id) if creator_group_id else None,
            viewer_group_id=viewer_group_id,
        )

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

        _publish_message_event(chat, chat_id, message)

        return True
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting chat {err}')
