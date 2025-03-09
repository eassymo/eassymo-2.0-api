from pydantic import BaseModel, Field, model_validator
from enum import Enum
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Union, Optional
from bson import ObjectId
from app.schemas.Groups import GroupSchema
from app.schemas.Roles import RolesSchema


class TeamMemberInviteStatus(Enum):
    SENT = "SENT"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"


class TeamMemberInviteStatusChange(BaseModel):
    status: TeamMemberInviteStatus = Field(None)
    timestamp: datetime = Field(datetime.now(ZoneInfo('UTC')))

    def toJson(self):
        data = self.model_dump()
        data["status"] = self.status.value
        data["timestamp"] = str(self.timestamp)
        return data


class TeamMemberInvite(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    inviter_user: str = Field(None, description="user that invited the person")
    group: Union[str, GroupSchema] = Field(
        None, description="group that they will be added to")
    role: Union[str, RolesSchema] = Field(
        None, description="the id of the role that they are configured to have")
    timestamp: datetime = Field(datetime.now(ZoneInfo('UTC')))
    contact_method: Optional[str] = Field(
        None, description="The method used to contact them")
    status_changes: Optional[List[TeamMemberInviteStatusChange]] = Field(
        [], description="list of status changes trough the time")
    is_public: bool = Field(False, description="Property that marks if it was a generated link")

    @model_validator(mode='before')
    @classmethod
    def convert_objectId(cls, values):
        if values is None:
            return {}
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values['_id'] = str(values['_id'])
        return values

    def toJson(self):
        data = self.model_dump()
        data["timestamp"] = str(self.timestamp)
        status_changes = []

        if isinstance(self.group, GroupSchema):
            data["group"] = self.group.toJson()

        if isinstance(self.role, RolesSchema):
            data["role"] = self.role.toJson()

        for status in self.status_changes:
            status_changes.append(status.toJson())

        data["status_changes"] = status_changes

        return data

    def change_status(self, new_status: str):
        try:
            updated_date = datetime.now(ZoneInfo('UTC'))
            status = TeamMemberInviteStatus[new_status]

            self.status_changes.append(TeamMemberInviteStatusChange(
                status=status, timestamp=updated_date))
        except KeyError:
            return KeyError(f'{new_status} is not valid status')
