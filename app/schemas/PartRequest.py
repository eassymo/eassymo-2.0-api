from pydantic import BaseModel, Field
from typing import List
from app.schemas.GroupVehicle import GroupVehicle
from app.schemas.Location import Location
from app.schemas.Groups import GroupSchema
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional


class PartRequest(BaseModel):
    creatorGroup: str = Field(
        description="This is used as the group that is owner of the request")
    creatorUser: str = Field(
        description="This is used as the user that is the creator")
    vehicleInformation: GroupVehicle = Field(description="Info of vehicle")
    location: Optional[Location]
    createdAt: datetime = Field(default=datetime.now(ZoneInfo('UTC')))
    photos: Optional[List[str]] = Field(description="list of urls")
    updatedAt: Optional[datetime]
    subscribedSellers: Optional[List[GroupSchema]] = Field(
        description="List of groups that where selected for this request")
    isActive: bool = Field(default=True, description="This determines if the request is Active")
    part: Optional[object] = Field(default={}, description="Part description")
    
