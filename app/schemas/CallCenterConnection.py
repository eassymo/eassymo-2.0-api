from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from bson import ObjectId
from app.schemas.Groups import GroupSchema

class CallCenterConnection(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    callcenter_id: str = Field(None, description="Source group")
    group_id: str = Field(None, description="group that selected this callcenter")
    callenter_info: Optional[GroupSchema] = Field(None)
    created_at: datetime = Field(datetime.now(ZoneInfo('UTC')))

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

        if self.callenter_info != None:
            data["callcenter_info"] = self.callenter_info.toJson()
        return data