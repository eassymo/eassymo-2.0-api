from pydantic import BaseModel, Field, root_validator
from typing import List
from app.schemas.GroupVehicle import GroupVehicle
from app.schemas.Location import Location
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from bson import ObjectId
from enum import Enum


class PartRequestStatus(Enum):
    CREATED = 1,
    OFFER_SELECTED = 2,


class PartRequest(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    creatorGroup: str = Field(
        description="This is used as the group that is owner of the request")
    creatorUser: str = Field(
        description="This is used as the user that is the creator")
    vehicleId: str = Field(
        description="Id of the vehicle, this will be used to fetch the vehicle info from db")
    vehicleInformation: Optional[GroupVehicle] = Field(None,
                                                       description="Info of vehicle")
    """location: Optional[Location] = Field(
       None) """
    createdAt: Optional[datetime] = Field(
        default=datetime.now(ZoneInfo('UTC')))
    photos: Optional[List[str]] = Field([], description="list of urls")
    updatedAt: Optional[datetime] = Field(
        default=datetime.now(ZoneInfo('UTC')))
    subscribedSellers: Optional[List[str]] = Field(
        description="List of groups that where selected for this request")
    isActive: bool = Field(
        default=True, description="This determines if the request is Active")
    part: Optional[object] = Field(default={}, description="Part description")
    partList: Optional[List[object]] = Field(
        [], description="Optional part list")
    parent_request_uid: Optional[str] = Field("")
    status: PartRequestStatus = Field(PartRequestStatus.CREATED, description="Current status of part request")

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values["_id"] = str(values["_id"])
        return values
    
    def update_status(self, new_status: PartRequestStatus):
        self.status = new_status
        self.updatedAt = datetime.now(ZoneInfo('UTC'))

    def toJson(self):
        data = self.dict(by_alias=True)

        if self.vehicleInformation:
            data["vehicleInformation"] = self.vehicleInformation.toJson()

        data["createdAt"] = str(data["createdAt"])
        data["updatedAt"] = str(data["updatedAt"])

        return data


class PartRequestEdit(BaseModel):
    id: Optional[str] = Field(None)
    comment: Optional[str] = Field(None)
    amount: Optional[int] = Field(None)
    subscribedSellers: Optional[List[str]] = Field(None)

    def toJson(self):
        return self.dict(by_alias=True)
