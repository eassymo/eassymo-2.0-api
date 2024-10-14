from pydantic import BaseModel, Field, root_validator
from app.schemas.Offer import Offer
from app.schemas.PartRequest import PartRequest
from enum import Enum
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Optional
from bson import ObjectId
from uuid import uuid4
from zoneinfo import ZoneInfo


class OrderStatus(Enum):
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    READY_TO_BE_DISPATCHED = "READY_TO_BE_DISPATCHED"
    DISPATCHED = "DISPATCHED"
    RECIEVED = "RECIEVED"
    CANCELED = "CANCELED"


class StatusChange(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    status: OrderStatus = Field(None, description="Status of the order")
    timestamp: datetime = Field(datetime.now(ZoneInfo('UTC')))

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def toJson(self):
        data = self.dict(by_alias=True)

        data["status"] = self.status.value
        data["timestamp"] = str(self.timestamp)

        return data


def _generate_order_id():
    date = datetime.now()
    uuid = str(uuid4())

    return f'{date.day}-{date.month}-{str(date.year)[-2:]}-{uuid[-2:]}'


class Order(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    order_id: str = Field(_generate_order_id())
    offer: Offer = Field(None, description="Selected offer")
    part_request: PartRequest = Field(
        None, description="selected part request")
    status_history: List[StatusChange] = Field(default_factory=lambda: [StatusChange(
        status=OrderStatus.WAITING_FOR_CONFIRMATION, timestamp=datetime.now(ZoneInfo('UTC')))], description="list of the status changes")
    status: OrderStatus = Field(
        OrderStatus.WAITING_FOR_CONFIRMATION.value, description="Current status of order")
    creator_user: str = Field(
        None, description="The user creator of the order")
    group: str = Field(None, description="the group this order belongs to")
    created_at: datetime = Field(default=datetime.now(ZoneInfo('UTC')))

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def toJson(self):
        data = self.dict(by_alias=True)

        data["offer"] = self.offer.toJson()
        data["part_request"] = self.part_request.toJson()

        historical_status = []

        for histoic_status in self.status_history:
            historical_status.append(histoic_status.toJson())

        data["status_history"] = historical_status
        data["status"] = self.status.value
        data["created_at"] = str(self.created_at)

        return data

    def change_status(self, new_status: str):
        try:
            status = OrderStatus[new_status]
            self.status = status
            self.status_history.append(StatusChange(
                status=status, timestamp=datetime.now(ZoneInfo('UTC'))))
        except KeyError:
            return ValueError(detail=f'{new_status} is not a valid status')
