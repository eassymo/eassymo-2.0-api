from pydantic import BaseModel, Field, root_validator
from datetime import datetime
from app.schemas.Message import Message
from typing import List
from zoneinfo import ZoneInfo
from bson import ObjectId
from typing import Optional
from app.schemas.Groups import GroupSchema
from uuid import uuid4


class Chat(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    requestId: Optional[str] = Field(None,
        description="If this field is populated it means that the chat belongs to a part request")
    orderId: Optional[str] = Field(None,
        description="If this field is populated it means that the chat belongs to an order")
    groupId: str = Field(
        description="this is the group id of the creator of the chat")
    createdAt: datetime = Field(datetime.now(ZoneInfo('UTC')))
    updatedAt: datetime = Field(datetime.now(ZoneInfo('UTC')))
    messages: List[Message]
    group_info: Optional[GroupSchema] = Field(None)

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if "_id" in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def insert_message(self, message: Message):
        self.messages.append(message)
        self.updatedAt = datetime.now(ZoneInfo('UTC'))

    def toJson(self):
        data = self.dict(by_alias=True)

        data["createdAt"] = str(self.createdAt)
        data["updatedAt"] = str(self.updatedAt)

        if "group_info" in self:
            data["group_info"] = self.group_info.toJson()

        messages = []

        for message in self.messages:
            message_data = message.toJson()
            messages.append(message_data)

        data["messages"] = messages

        return data
