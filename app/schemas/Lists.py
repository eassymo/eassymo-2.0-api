from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, root_validator
from typing import List, Optional
from bson import ObjectId
from app.schemas.Groups import GroupSchema
from datetime import datetime

class ListsSchema(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    group_id: str = Field(description="group owner of the list")
    user_uid: str = Field(description="user owner of the list")
    groups: List[str] = Field(description="Groups belonging to this list")
    name: str = Field(description="Name of the list")
    is_priority: bool = Field(
        description="this field determines if it is a priority")
    groups_info: Optional[List[GroupSchema]] = Field(None)
    is_favorite: Optional[bool] = Field(default=False, description="If True then the list is favorite")
    last_modified: Optional[datetime]= Field(default=datetime.now(ZoneInfo('UTC')))

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def append_group(self, new_group: str):
        self.groups.append(new_group)

    def toJson(self):
        data = self.model_dump(by_alias=True)

        if self.groups_info != None and len(self.groups_info) > 0:
            groups = []
            for group in self.groups_info:
                groups.append(group.toJson())

            data["groups_info"] = groups

        if self.last_modified != None:
            data["last_modified"] = str(self.last_modified)

        return data
