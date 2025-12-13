from datetime import datetime
from zoneinfo import ZoneInfo
from bson import ObjectId
from pydantic import BaseModel, Field, root_validator
from typing import Optional
from app.schemas.Offer import OfferStatus


class OfferStatusByGroup(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    group_id: str = Field(
        None, description="id of the group that holds this status")
    offer_id: str = Field(
        None, description="id of the offer that is linked to this")
    createdAt: Optional[datetime] = Field(datetime.now(ZoneInfo('UTC')))
    updatedAt: Optional[datetime] = Field(
        default=datetime.now(ZoneInfo('UTC')))
    status: OfferStatus = Field(None)

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values["_id"] = str(values["_id"])

        if 'createdAt' not in values or values['createdAt'] is None:
            values['createdAt'] = datetime.now(ZoneInfo('UTC'))
        if 'updatedAt' not in values or values['updatedAt'] is None:
            values['updatedAt'] = datetime.now(ZoneInfo('UTC'))

        return values

    def toJson(self):

        data = self.model_dump(by_alias=True)
        data["createdAt"] = str(self.createdAt)
        data["updatedAt"] = str(self.updatedAt)
        data["status"] = self.status.value

        return data
