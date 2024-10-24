from pydantic import BaseModel, Field, root_validator
from enum import Enum
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List
from uuid import uuid4
from typing import Optional


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"
    LINK = "link"


class MessageMetaData(BaseModel):
    groupName: str = Field(
        None, description="name of the group that is sending the message")
    senderName: str = Field(None, description="name of the sender")


class Link(BaseModel):
    displayName: str = Field(None, description="display the name of the link")
    path: str = Field(None, description="path og the link")


class Message(BaseModel):
    uid: str = Field(str(uuid4()), description="message unique uid")
    type: MessageType = Field(None, description="type of message")
    chatId: str = Field("reference to the chat id of firebase")
    groupId: str = Field("the owner group id of the chat")
    senderId: str = Field("the _id of the user that sent the message")
    content: str = Field("text content of the message")
    createdAt: datetime = Field(datetime.now(
        ZoneInfo('UTC')), description="timestamp")
    attachments: List[str] = Field(
        [], description="attachments in the form of strings Eg: urls")
    isRead: bool = Field(False, description="is this message read")
    metaData: MessageMetaData = Field(
        None, description="meta data of messages")
    link: Optional[Link] = Field(None, description="Link embedded in message")
    usersThatRead: Optional[dict] = Field(None, description="Key value pair object that stores the users that have read certain message")

    def toJson(self):
        data = self.dict()

        data["type"] = self.type.value
        data["createdAt"] = str(self.createdAt)
        data["metaData"] = self.metaData.dict() if self.metaData is not None else None
        data["link"] =  self.link.dict() if self.link is not None else None

        return data
