from pydantic import BaseModel, Field, root_validator
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from bson import ObjectId


class GroupVehicle(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    year: str = Field(
        description="This indicates the production year of the car")
    maker: str = Field(description="This indicates the maker of the car")
    model: str = Field(description="This indicates the model")
    engine: str = Field()
    group: str = Field(description="Group owner of this vehicle")
    user: str = Field(description="User owner of this vehicle")
    subModel: Optional[str] = Field(description="SubModel if available")
    active: Optional[bool] = Field(
        default=True, description="Field to determine if its active")
    createdAt: Optional[datetime] = Field(
        default=datetime.now(ZoneInfo('UTC')))
    
    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if "_id" in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def toJson(self):
        data = self.dict(by_alias=True)

        data["createdAt"] = str(data["createdAt"])
        return data
