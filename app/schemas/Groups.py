from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
from typing import Optional, List

class GroupType(Enum):
    SELLER=2
    BUYER=1

class GroupSchema(BaseModel):
    name: str = Field(None, min_length=3, max_length=100, description="Name of the group")
    type: int = Field(None, description="Type of group")
    whatsAppNumber:  Optional[str] = Field(None, description="Whatsapp number")
    state: str = Field(None, description="location state of group")
    city: str = Field(None, description="location city of the group")
    country: Optional[str] = Field("Mexico", description="country of the group")
    location: Optional[object] = Field(None, description="location lat lng of the group")
    phone:  Optional[str] = Field(None, description="")
    email:  Optional[str] = Field(None, description="email")
    webPage:  Optional[str] = Field(None, description="Web page of the group")
    since:  Optional[datetime] = Field(None, description="Date from when the user actually started their business")
    story:  Optional[str] = Field(None, description="Story of the business")
    isActive:  Optional[bool] = Field(True, description="to see if group is active")
    address:  Optional[str] = Field(None, description="address of the group")
    group_store_type: int = Field(None, description="store type of the group")
    users: Optional[List[str]] = Field(None, description="users linked to this group")
    owner: Optional[str] = Field(None, description="User owner") 