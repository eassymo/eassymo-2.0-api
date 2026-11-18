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
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(ZoneInfo('UTC')))

    @model_validator(mode="before")
    @classmethod
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        # Legacy Roles store `value` as a number (215); assignments hold it as text.
        if isinstance(values.get("role"), int) and not isinstance(values.get("role"), bool):
            values["role"] = str(values["role"])
        return values
    
    
    def toJson(self):
        data = self.model_dump(by_alias=True)
        if data.get("_id") is None:
            # A null _id would be stored as-is and every later insert would collide with it.
            data.pop("_id", None)

        if "created_at" in data:
            data["created_at"] = str(self.created_at)
        return data
