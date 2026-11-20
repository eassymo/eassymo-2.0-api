from datetime import datetime
from enum import Enum
from typing import List, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.utils.datetime_utils import serialize_datetime

DELIVERY_FAILURE_MAX_PHOTOS = 5
DELIVERY_FAILURE_MAX_NOTE_LEN = 500


class DeliveryFailureReason(str, Enum):
    NO_ANSWER = "no_answer"
    WRONG_ADDRESS = "wrong_address"
    NOBODY_TO_RECEIVE = "nobody_to_receive"
    OTHER = "other"


class DeliveryFailure(BaseModel):
    """One failed delivery attempt. The order's status does not change."""

    reason: DeliveryFailureReason
    note: Optional[str] = None
    photo_urls: List[str] = Field(default_factory=list)
    at: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo("UTC")))
    # Who reported it: {"type": "group_member", "user_id"} or {"type": "guest", "name"}; never the token.
    by: dict = Field(default_factory=dict)
    client_attempt_id: Optional[str] = None

    def toJson(self):
        data = self.model_dump()
        data["reason"] = self.reason.value
        data["at"] = serialize_datetime(self.at)
        return data
