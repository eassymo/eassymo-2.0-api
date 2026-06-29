from pydantic import BaseModel, Field, model_validator
from typing import Optional
from bson import ObjectId
from datetime import datetime
from zoneinfo import ZoneInfo


class UserRoles(BaseModel):
    id: Optional[str]= Field(alias="_id", default=None)
    user_uid: str = Field(description="id of the user")
    role: str = Field(description="the role value")
    group: Optional[str] = Field(
        None, description="the group the user has the role assigned to")
    active: bool = Field(False, description="Wether the user role is active")
    created_at: Optional[datetime] = Field(datetime.now(ZoneInfo('UTC')))

    @model_validator(mode="before")
    @classmethod
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        return values
    
    
    def toJson(self):
        data = self.model_dump(by_alias=True)

        if "created_at" in data:
            data["created_at"] = str(self.created_at)
        return data
