from pydantic import BaseModel, Field, root_validator
from typing import List
from app.schemas.GroupVehicle import GroupVehicle
from app.schemas.Groups import GroupSchema
from app.schemas.Offer import Offer
from app.schemas.Location import Location
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from bson import ObjectId
from enum import Enum


class PartRequestStatus(Enum):
    CREATED = "Created"
    OFFER_SELECTED = "Offer_selected"
    PENDING = "Pending"


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
    createdAt: Optional[datetime] = Field(None)
    photos: Optional[List[str]] = Field([], description="list of urls")
    updatedAt: Optional[datetime] = Field(None)
    subscribedSellers: Optional[List[str]] = Field(
        description="List of groups that where selected for this request")
    isActive: bool = Field(
        default=True, description="This determines if the request is Active")
    part: Optional[object] = Field(default={}, description="Part description")
    partList: Optional[List[object]] = Field(
        [], description="Optional part list")
    parent_request_uid: Optional[str] = Field("")
    specific_order_uid: Optional[str] = Field(None, description="This id groups the different part requests as a single order, independent to the vehicle")
    status: PartRequestStatus = Field(
        default=PartRequestStatus.CREATED.value, description="Current status of part request")
    show_ranking: Optional[bool] = Field(
        None, description="this is a field that is calculated in the runtime to determine if we should show the ranking for all users")
    group_info: Optional[GroupSchema] = Field(None, description="detailed information of the group")
    offers_amount: Optional[int] = Field(None)

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values["_id"] = str(values["_id"])
        
        if 'createdAt' not in values or values['createdAt'] is None:
            values['createdAt'] = datetime.now(ZoneInfo('UTC'))
        if 'updatedAt' not in values or values['updatedAt'] is None:
            values['updatedAt'] = datetime.now(ZoneInfo('UTC'))
            
        return values

    def update_status(self, new_status: PartRequestStatus):
        self.status = new_status
        self.updatedAt = datetime.now(ZoneInfo('UTC'))

    def toJson(self):
        data = self.dict(by_alias=True)

        if self.vehicleInformation:
            data["vehicleInformation"] = self.vehicleInformation.toJson()

        if self.group_info:
            data["group_info"] = self.group_info.toJson()

        data["createdAt"] = self.createdAt.isoformat() if self.createdAt else None
        data["updatedAt"] = self.updatedAt.isoformat() if self.updatedAt else None

        if data.get("status") != None:
            data["status"] = self.status.value

        return data


class PartRequestEdit(BaseModel):
    id: Optional[str] = Field(None)
    comment: Optional[str] = Field(None)
    amount: Optional[int] = Field(None)
    subscribedSellers: Optional[List[str]] = Field(None)

    def toJson(self):
        return self.dict(by_alias=True)
