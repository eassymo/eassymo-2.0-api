from pydantic import BaseModel, Field, field_validator, root_validator
from typing import List
from app.schemas.GroupVehicle import GroupVehicle
from app.schemas.Groups import GroupSchema
from app.schemas.Offer import Offer
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from bson import ObjectId
from enum import Enum


class PartRequestStatus(Enum):
    CREATED = "Created"
    OFFER_SELECTED = "Offer_selected"
    PENDING = "Pending"
    NO_INVENTORY = "No_Inventory"
    REJECTED = "Rejected"


class FulfillmentType(str, Enum):
    delivery = "delivery"
    pickup = "pickup"


class DeliveryAddress(BaseModel):
    address: Optional[str] = Field(None)
    lat: Optional[float] = Field(None)
    lng: Optional[float] = Field(None)
    state: Optional[str] = Field(None)
    city: Optional[str] = Field(None)
    postalCode: Optional[str] = Field(None)


class DeliveryContact(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=1, max_length=30)


class NonCompatibleSeller(BaseModel):
    group_id: str = Field(..., description="Seller group excluded from this part request")
    reason: str = Field(..., description="Why the seller does not match armadora/sistemas rules")

    @field_validator("group_id", "reason", mode="before")
    @classmethod
    def _strip_whitespace(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


def delivery_address_is_meaningful(addr: Optional[DeliveryAddress]) -> bool:
    if addr is None:
        return False
    if addr.address and str(addr.address).strip():
        return True
    if addr.lat is not None and addr.lng is not None:
        return True
    return False


def validate_delivery_fulfillment(
    fulfillment_type: FulfillmentType,
    delivery_address: Optional[DeliveryAddress],
    delivery_contact: Optional[DeliveryContact],
) -> None:
    if fulfillment_type == FulfillmentType.pickup:
        return
    if delivery_contact is None:
        raise ValueError(
            "delivery_contact is required when fulfillment_type is delivery"
        )
    name = (delivery_contact.name or "").strip()
    phone = (delivery_contact.phone or "").strip()
    if not name or not phone:
        raise ValueError(
            "delivery_contact name and phone are required when fulfillment_type is delivery"
        )
    if not delivery_address_is_meaningful(delivery_address):
        raise ValueError(
            "delivery_address is required when fulfillment_type is delivery (address or lat/lng)"
        )


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
    createdAt: Optional[datetime] = Field(None)
    photos: Optional[List[str]] = Field([], description="list of urls")
    updatedAt: Optional[datetime] = Field(None)
    subscribedSellers: Optional[List[str]] = Field(
        description="List of groups that where selected for this request")
    nonCompatibleSellers: Optional[List[NonCompatibleSeller]] = Field(
        default=None,
        description="Buyer-selected sellers excluded by armadora/sistemas compatibility for this part",
    )
    subscribedFollowers: Optional[List[str]] = Field(
        None,
        description="Groups auto-merged from the creator's followers list. Read-only in chat.",
    )
    isActive: bool = Field(
        default=True, description="This determines if the request is Active")
    part: Optional[object] = Field(default={}, description="Part description")
    partList: Optional[List[object]] = Field(
        [], description="Optional part list")
    parent_request_uid: Optional[str] = Field("")
    specific_order_uid: Optional[str] = Field(
        None, description="This id groups the different part requests as a single order, independent to the vehicle")
    status: PartRequestStatus = Field(
        default=PartRequestStatus.CREATED.value, description="Current status of part request")
    show_ranking: Optional[bool] = Field(
        None, description="this is a field that is calculated in the runtime to determine if we should show the ranking for all users")
    group_info: Optional[GroupSchema] = Field(
        None, description="detailed information of the group")
    offers_amount: Optional[int] = Field(None)
    commissioner_group: Optional[str] = Field(None)
    fulfillment_type: FulfillmentType = Field(
        default=FulfillmentType.delivery,
        description="delivery: ship to delivery_address; pickup: buyer collects at seller",
    )
    delivery_address: Optional[DeliveryAddress] = Field(None)
    delivery_contact: Optional[DeliveryContact] = Field(None)
    offers: Optional[Offer] = Field(default=None, exclude=True)
    origin: Optional[str] = Field(
        "marketplace", description="marketplace | mostrador")
    mostrador_folio_id: Optional[str] = Field(None)
    mostrador_piece_id: Optional[str] = Field(None)

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values["_id"] = str(values["_id"])

        # Rows with id="" break joins (offer.request_id == part_request.id) in CommissionerService / PartRequestService.
        if isinstance(values, dict) and values.get("id") in ("", None):
            values.pop("id", None)

        if 'createdAt' not in values or values['createdAt'] is None:
            values['createdAt'] = datetime.now(ZoneInfo('UTC'))
        if 'updatedAt' not in values or values['updatedAt'] is None:
            values['updatedAt'] = datetime.now(ZoneInfo('UTC'))

        if values.get("fulfillment_type") is None:
            values["fulfillment_type"] = FulfillmentType.delivery.value

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

        if self.offers != None and len(self.offers) > 0:
            data["offers"] = [offer.toJson() for offer in self.offers]

        data["createdAt"] = self.createdAt.isoformat() if self.createdAt else None
        data["updatedAt"] = self.updatedAt.isoformat() if self.updatedAt else None

        if data.get("status") is not None:
            status = self.status
            data["status"] = status.value if isinstance(status, PartRequestStatus) else status

        fulfillment = self.fulfillment_type
        data["fulfillment_type"] = (
            fulfillment.value if isinstance(fulfillment, FulfillmentType) else fulfillment
        )

        return data


class PartRequestEdit(BaseModel):
    id: Optional[str] = Field(None)
    comment: Optional[str] = Field(None)
    amount: Optional[int] = Field(None)
    subscribedSellers: Optional[List[str]] = Field(None)
    fulfillment_type: Optional[FulfillmentType] = Field(None)
    delivery_address: Optional[DeliveryAddress] = Field(None)
    delivery_contact: Optional[DeliveryContact] = Field(None)

    def toJson(self):
        return self.dict(by_alias=True)


class PartRequestGroupedByDate(BaseModel):
    date: str = Field(None)
    part_requests: List[PartRequest] = Field([])

    def toJson(self):
        data = self.model_dump()

        if len(self.part_requests) > 0:
            data["part_requests"] = [part_request.toJson()
                                     for part_request in self.part_requests]
        return data
