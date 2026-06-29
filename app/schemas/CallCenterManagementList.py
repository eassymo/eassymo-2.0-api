from pydantic import BaseModel, model_validator, Field
from typing import Optional, List, Union
from datetime import datetime
from zoneinfo import ZoneInfo
from bson import ObjectId
from app.schemas.Groups import GroupSchema

class CallCenterManagementList(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    name: str = Field(None, description="Name of the list")
    description: Optional[str] = Field(
        None, description="Description of the list")
    callcenter_id: str = Field(None, description="call center id")
    user_uid: Optional[str] = Field(None, description="uid of the user in case the list is private")
    groups: List[Union[str, GroupSchema]] = Field([], description="List of group IDs or group objects")
    created_at: datetime = Field(datetime.now(ZoneInfo('UTC')))
    active: bool = Field(True)

    @model_validator(mode="before")
    @classmethod
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def toJson(self):
        data = self.model_dump(by_alias=True)

        data["created_at"] = str(self.created_at)

        groups_objects = []
        for group in self.groups:
            if isinstance(group, GroupSchema):
                groups_objects.append(group.toJson())
            elif isinstance(group, str):
                groups_objects.append(group)
            
        if len(groups_objects) > 0:
            data["groups"] = groups_objects

        return data
