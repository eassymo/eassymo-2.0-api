from app.repositories import ChatRepository as chatRepository
from app.schemas.Chat import Chat
from app.schemas.Message import Message
from pymongo.errors import PyMongoError
from fastapi import HTTPException
from bson import ObjectId


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


def to_be_read(id: str, userUid: str, type: str):
    try:
        filters = {}
        chat_data: any
        number_of_messages_to_be_read = 0
        if type == "request":
            filters = {"requestId": id}
        else:
            filters = {"orderId": id}

        try:
            chat_data = list(chatRepository.find(filters))[0]
            chat = Chat(**chat_data)

            for message in chat.messages:
                has_been_read = message.usersThatRead.get(
                    userUid) if message.usersThatRead is not None else True
                if has_been_read == False:
                    number_of_messages_to_be_read += 1
        except Exception as e:
            raise Exception(f'Error while counting not read messages {e}')

        return number_of_messages_to_be_read
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding chat {err}')


def read_messages(id: str, user_uid: str, type: str):
    try:
        filters = {}

        if type == "request":
            filters = {"requestId": id}
        else:
            filters = {"orderId": id}

        chat_data = list(chatRepository.find(filters))[0]
        chat = Chat(**chat_data)

        for message in chat.messages:
            if message.usersThatRead is not None:
                if user_uid in message.usersThatRead:
                    message.usersThatRead[user_uid] = True
            else:
                message.usersThatRead = {user_uid: True}

        chat_json = chat.toJson()
        chat_id = ObjectId(chat_json["_id"])
        chat_json.pop("_id")
        chatRepository.update_chat(chat_id, chat_json)

        return True
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while reading messages {err}')


def add_message(message: Message):
    try:
        chat_id = ObjectId(message.chatId)
        chat_data = chatRepository.find_by_id(chat_id)
        chat = Chat(**chat_data)

        chat.insert_message(message)

        chat_json = chat.toJson()

        chat_json.pop("_id")

        chatRepository.update_chat(chat_id, chat_json)

        return True
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting chat {err}')
