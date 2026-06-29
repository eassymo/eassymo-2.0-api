from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
from bson import ObjectId
from pydantic import BaseModel, Field, root_validator


class PreloadedFiltersTypes(str, Enum):
    multiple_offers = "multiple_offers"
    dynamic_offer_selection = "dynamic_offer_selection"


class PreloadedFilters(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    type: PreloadedFiltersTypes = Field(
        None, description="this determines where the preloaded filters should be applied")
    values: Dict[str, Any] = Field({})
    user_uid: str = Field(None, description="Uid of the user that saved this")
    group_id: str = Field(
        None, description="Id of the group that this is linked to")
    created_at: Optional[datetime] = Field(default=datetime.now(ZoneInfo('UTC')))

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values["_id"] = str(values["_id"])

        if 'createdAt' not in values or values['created_at'] is None:
            values['created_at'] = datetime.now(ZoneInfo('UTC'))

        return values

    def toJson(self):
        data = self.dict(by_alias=True)

        data["created_at"] = self.created_at.isoformat() if self.created_at else None

        if data.get("type") != None:
            data["type"] = self.type.value

        return data
