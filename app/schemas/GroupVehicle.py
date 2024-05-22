from pydantic import BaseModel, Field
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional


class GroupVehicle(BaseModel):
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
