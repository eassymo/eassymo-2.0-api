from pydantic import BaseModel, Field, root_validator
from enum import Enum
from datetime import datetime
from typing import Optional, List
from bson import ObjectId


class GroupType(Enum):
    CAR_SHOP = 2
    PARTS_STORE = 1


class GroupSchema(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    name: str = Field(None, min_length=3, max_length=100,
                      description="Name of the group")
    type: int = Field(None, description="Type of group")
    whatsAppNumber:  Optional[str] = Field(None, description="Whatsapp number")
    state: str = Field(None, description="location state of group")
    city: str = Field(None, description="location city of the group")
    country: Optional[str] = Field(
        "Mexico", description="country of the group")
    location: Optional[object] = Field(
        None, description="location lat lng of the group")
    phone:  Optional[str] = Field(None, description="")
    email:  Optional[str] = Field(None, description="email")
    webPage:  Optional[str] = Field(None, description="Web page of the group")
    since:  Optional[str] = Field(
        None, description="Date from when the user actually started their business")
    story:  Optional[str] = Field(None, description="Story of the business")
    isActive:  Optional[bool] = Field(
        True, description="to see if group is active")
    address:  Optional[str] = Field(None, description="address of the group")
    group_store_type: int = Field(None, description="store type of the group")
    users: Optional[List[str]] = Field(
        None, description="users linked to this group")
    owner: Optional[str] = Field(None, description="User owner")
    can_be_invited: Optional[bool] = Field(None)

    @root_validator(pre=True)
    def convert_objectId(cls, value):
        if "_id" in value and isinstance(value["_id"], ObjectId):
            value["_id"] = str(value["_id"])
        return value

    def add_user_to_group(self, new_user: str):
        current_user_list = self.users
        current_user_list.append(new_user)
        self.users = list(set(current_user_list))

    def remove_user_from_group(self, user_id: str):
        current_user_list = self.users
        current_user_list.remove(user_id)
        self.users = list(set(current_user_list))

    def toJson(self):
        data = self.dict(by_alias=True)
        return data
