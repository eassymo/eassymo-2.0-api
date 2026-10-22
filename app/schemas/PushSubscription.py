from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PushSubscriptionCreate(BaseModel):
    token: str = Field(..., min_length=1)
    userAgent: Optional[str] = None
    groupId: Optional[str] = None


class PushSubscriptionDelete(BaseModel):
    token: Optional[str] = None


class PushDispatchRequest(BaseModel):
    type: str
    message: str
    ownerGroup: str
    owner: str
    metaData: Optional[dict] = None
    visibleRoles: Optional[list[str]] = None
    uid: Optional[str] = None
    navigateToUrl: Optional[str] = None
    read: Optional[bool] = False
    callcenterId: Optional[str] = None
    callcenterName: Optional[str] = None
