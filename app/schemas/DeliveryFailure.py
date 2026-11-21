from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.utils.datetime_utils import serialize_datetime

DELIVERY_FAILURE_MAX_PHOTOS = 5
DELIVERY_FAILURE_MAX_NOTE_LEN = 500


class DeliveryFailureReason(str, Enum):
    NO_ANSWER = "no_answer"
    WRONG_ADDRESS = "wrong_address"
    NOBODY_TO_RECEIVE = "nobody_to_receive"
    STORE_CLOSED = "store_closed"
    NOT_READY = "not_ready"
    WRONG_ITEM = "wrong_item"
    DAMAGED = "damaged"
    OTHER = "other"


FAILURE_KINDS = ("pickup", "delivery")
PICKUP_REASONS = {"store_closed", "not_ready", "wrong_item", "damaged", "other"}
DELIVERY_REASONS = {"no_answer", "wrong_address", "nobody_to_receive", "other"}


def reasons_for(kind: str) -> set:
    return PICKUP_REASONS if kind == "pickup" else DELIVERY_REASONS


def open_issue(failures: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """The order's open issue: its last failure when that one has no resolution yet.
    Failures recorded before issues existed have no "resolution" key and are never open."""
    if not failures:
        return None
    last = failures[-1]
    if "resolution" in last and last["resolution"] is None:
        return last
    return None


class DeliveryFailure(BaseModel):
    """One failed delivery attempt. The order's status does not change."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: str = "delivery"  # "pickup" | "delivery"
    reason: DeliveryFailureReason
    # Set when someone resolves it: {action, by: {role, uid}, note, at}. None = open issue.
    resolution: Optional[dict] = None
    return_requested: bool = False  # the store asked the rider to bring the parcel back
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
