from pydantic import BaseModel, Field, model_validator
from typing import Optional
from bson import ObjectId
from datetime import datetime
from zoneinfo import ZoneInfo
from enum import Enum


class GuestDeliveryProfileStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class GuestDeliveryProfile(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    phone: str = Field(..., description="E.164 phone number, unique per profile")
    name: str = Field(..., description="Guest display name")
    token: str = Field(..., description="UUID credential — never expires unless revoked")
    created_at: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo('UTC')))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo('UTC')))
    status: GuestDeliveryProfileStatus = Field(GuestDeliveryProfileStatus.ACTIVE)
    accepted_at: Optional[datetime] = Field(None)

    @model_validator(mode="before")
    @classmethod
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values['_id'] = str(values['_id'])
        return values

    def toJson(self):
        data = self.model_dump(by_alias=True)
        data['created_at'] = str(self.created_at)
        data['updated_at'] = str(self.updated_at)
        if self.accepted_at:
            data['accepted_at'] = str(self.accepted_at)
        return data
