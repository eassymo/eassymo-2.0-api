from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime
from zoneinfo import ZoneInfo

# TODO: THE BRANDS ARE A DIFFERENT COLLECTION


class Offer(BaseModel):
    class OfferType(Enum):
        partOffer = "PartOffer"

    class OfferStatus(Enum):
        created = "Created"
    request_id: str = Field(
        description="This is the request that is the owner of this offer")
    user_uid: str = Field(description="Creator user of the offer")
    group_id: str = Field(description="group that created the offer")
    offer_group_uid: Optional[str] = Field(default=None,
                                           description="This is the uid that will be used in case this offer has sub offers")
    brand: str = Field(
        description="This is the brand of the offered part or item")
    guarantee: str = Field(description="Guarantee of the offered part")
    price: float = Field(description="price")
    unit_of_measure: str = Field(description="Unit of measure of item offered")
    to_be_delivered_time: Optional[datetime] = Field(
        default=datetime.now(ZoneInfo('UTC')))
    code: Optional[str] = Field(description="code of item")
    location: Optional[object] = Field(
        default= None,
        description="this will be the location of the part")
    photos: Optional[List[str]] = Field(
        default= [],
        description="List of urls of the pictures")
    internalComments: Optional[str] = Field(
        description="Comments to be only displayed to the offer creator group")
    publicComments: Optional[str] = Field(
        description="Comments to be diaplayed to the user that created the request"
    )
    status: OfferStatus = Field(
        default=OfferStatus.created.value, description="Status of the offer")
    type: OfferType = Field(default=OfferType.partOffer.value)
