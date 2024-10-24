from app.config import database
from bson import ObjectId


def insert(chat_payload):
    return database.db["Chats"].insert_one(chat_payload)

def find(filters):
    return database.db["Chats"].find(filters)

def find_by_id(id: ObjectId):
    return database.db["Chats"].find_one({"_id": id})


def find_by_request_id(request_id: str):
    aggregation = [
        {
            "$match": {"requestId": request_id}
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"group_id": {"$toObjectId": "$groupId"}},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$_id", "$$group_id"]}
                        }
                    }
                ],
                "as": "group_info"
            }
        },
        {
            "$unwind": {
                "path": "$group_info",
                "preserveNullAndEmptyArrays": True
            }
        }
    ]
    return database.db["Chats"].aggregate(aggregation)


def find_by_order_id(order_id: str):
    aggregation = [
        {
            "$match": {"orderId": order_id}
        },
        {
            "$lookup": {
                "from": "groups",
                "let": {"group_id": {"$toObjectId": "$groupId"}},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$_id", "$$group_id"]}
                        }
                    }
                ],
                "as": "group_info"
            }
        },
        {
            "$unwind": {
                "path": "$group_info",
                "preserveNullAndEmptyArrays": True
            }
        }
    ]
    return database.db["Chats"].aggregate(aggregation)


def find_to_be_read(filters):
    chat = database.db["Chats"].find_one(filters)
    if chat and "messages" in chat:
        unread_messages = [msg for msg in chat["messages"] if msg.get("isRead") == False]
        return len(unread_messages)
    return 0


def update_chat(id: ObjectId, chat_payload: dict):
    return database.db["Chats"].update_one({"_id": id}, {"$set": {**chat_payload}})
