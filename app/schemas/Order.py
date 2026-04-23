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
from app.schemas.PartRequest import PartRequest
from app.schemas.Groups import GroupSchema


class DeliveryAssignmentType(str, Enum):
    GROUP_MEMBER = "group_member"
    GUEST = "guest"


class DeliveryAssignment(BaseModel):
    type: DeliveryAssignmentType = Field(..., description="Whether assigned to a group member or a guest")
    user_id: Optional[str] = Field(None, description="User _id — only for type=group_member")
    guest_token: Optional[str] = Field(None, description="UUID token — only for type=guest")
    guest_name: Optional[str] = Field(None)
    guest_phone: Optional[str] = Field(None, description="E.164 format")
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo('UTC')))

    def toJson(self):
        data = self.model_dump()
        data["type"] = self.type.value
        data["assigned_at"] = str(self.assigned_at)
        return data


class OrderStatus(Enum):
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    READY_TO_BE_DISPATCHED = "READY_TO_BE_DISPATCHED"
    WAITING_FOR_COLLECTION = "WAITING_FOR_COLLECTION"
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

    return f'{date.day}-{date.month}-{str(date.year)[-2:]}-{uuid[-4:]}'


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
    to_be_delivered_time: Optional[datetime] = Field(
        None, description="Once confirmed this is the time the order is promised to be delivered")
    current_deliver_promise_delayed: Optional[bool] = Field(
        None, description="This is marked as true in case the new deliver promise is greater than the previous promise time")
    updated_at: datetime = Field(default=datetime.now(ZoneInfo('UTC')))
    offer_group: Optional[GroupSchema] = Field(None)
    request_group: Optional[GroupSchema] = Field(None)
    delivery_notes_buyer: Optional[str] = Field(None)
    delivery_pictures_buyer: Optional[List[str]] = Field([])
    delivery_notes_seller: Optional[str] = Field(None)
    delivery_pictures_seller: Optional[List[str]] = Field([])
    packaged_notes_seller: Optional[str] = Field(None)
    packaged_pictures_seller: Optional[List[str]] = Field([])
    delivery_assignment: Optional[DeliveryAssignment] = Field(None)

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

        if self.offer_group != None:
            data["offer_group"] = self.offer_group.toJson()

        if self.request_group != None:
            data["request_group"] = self.request_group.toJson()

        data["status_history"] = historical_status
        data["status"] = self.status.value
        data["updated_at"] = str(self.updated_at)
        data["created_at"] = str(self.created_at)

        if self.to_be_delivered_time != None:
            data["to_be_delivered_time"] = str(self.to_be_delivered_time)

        if self.delivery_assignment is not None:
            data["delivery_assignment"] = self.delivery_assignment.toJson()

        return data

    def change_status(self, new_status: str):
        try:
            updated_date = datetime.now(ZoneInfo('UTC'))
            status = OrderStatus[new_status]
            self.status = status
            self.status_history.append(StatusChange(
                status=status, timestamp=updated_date))
            self.updated_at = updated_date
        except KeyError:
            return KeyError(detail=f'{new_status} is not a valid status')

    def change_delivery_time(self, new_date: datetime, current_deliver_promise_delayed: bool):
        try:
            self.to_be_delivered_time = new_date
            self.updated_at = datetime.now(ZoneInfo('UTC'))
            self.current_deliver_promise_delayed = current_deliver_promise_delayed
        except Exception as e:
            raise ValueError(detail=f'Error while changing delivery time {e}')
