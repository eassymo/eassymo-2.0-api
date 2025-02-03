from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from zoneinfo import ZoneInfo
from enum import Enum
from typing import List, Optional, Dict, Any
from bson import ObjectId


class RequestInviteStatus(Enum):
    CREATED = "CREATED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"


class StatusChange(BaseModel):
    status: RequestInviteStatus = Field(None)
    time: datetime = Field(
        default_factory=lambda: datetime.now(ZoneInfo('UTC')))

    def to_json(self):
        data = self.model_dump()
        data["status"] = self.status.value
        data["time"] = str(self.time)

        return data


class RequestInvite(BaseModel):
    id: str = Field(None, alias="_id")
    parent_request_id: str = Field(
        description="Id of the parent request that groups the requests that the user should join")
    inviter_group: str = Field(
        description="Group that was logged in that invited that group")
    inviter_user: str = Field(description="user that invited the other group")
    invited_group: Optional[str] = Field(
        None, description="group that was invited")
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(ZoneInfo('UTC')))
    status_history: List[StatusChange] = Field(default_factory=lambda: [StatusChange(
        status=RequestInviteStatus.CREATED, time=datetime.now(ZoneInfo('UTC')))], description="list of the status changes")
    status: RequestInviteStatus = Field(
        RequestInviteStatus.CREATED, description="current status of invite")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(ZoneInfo('UTC')))
    census_id: Optional[str] = Field(
        None, description="it only applies if it was originally for a census item")

    @model_validator(mode='before')
    @classmethod
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def change_status(self, new_status: str):
        try:
            updated_date = datetime.now(ZoneInfo('UTC'))
            status = RequestInviteStatus[new_status]

            self.status = status
            self.status_history.append(StatusChange(
                status=status, time=updated_date))
            self.updated_at = updated_date
        except KeyError:
            return KeyError(detail=f'{new_status} is not a valid status')

    def toJson(self) -> Dict[str, Any]:
        data = self.model_dump(by_alias=True)

        data["created_at"] = str(self.created_at)

        status_changes = []
        for status_change in self.status_history:
            status_changes.append(status_change.to_json())
        data["status_history"] = status_changes

        data["status"] = self.status.value
        data["updated_at"] = str(self.updated_at)
        return data
