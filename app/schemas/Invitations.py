from pydantic import BaseModel, Field, root_validator
from enum import Enum
from app.schemas.Census import CensusSchema
from datetime import datetime
from bson import ObjectId
from typing import Optional, Any, Dict
from zoneinfo import ZoneInfo

class InvitationStatus(Enum):
    SENT = "SENT"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"


class InvitationType(Enum):
    WHATSAPP = 1
    EMAIL = 2
    SMS = 3


class InvitationsSchema(BaseModel):
    id: str = Field(None, alias="_id")
    user: str = Field(None, description="User that originated the invite")
    userName: str = Field(None, description="Name of user sending invite")
    inviteStatus: InvitationStatus = Field(
        InvitationStatus.SENT, description="Status of the invite")
    censusUser: CensusSchema = Field(
        None, description="user of the census that the invite was sent to")
    type: InvitationType = Field(
        None, description="Type of communication method used")
    finalContactInfo: str = Field(
        None, description="Final contact information used in the invite")
    censusId: str = Field(None, description="Id of the census user")
    createdAt: datetime = Field(None, description="Timestamp of created time")
    lastSent: datetime = Field(
        None, description="Timestamp of when the invite was last sent")
    creator_group: str = Field(
        None, description="The id of the group that generated the invitation")
    whatsapp_message_data: Optional[Dict[str, Any]] = Field(None, description="The data returned from twilio")

    @root_validator(pre=True)
    def convert_objectId(cls, values):
        if '_id' in values and isinstance(values['_id'], ObjectId):
            values['_id'] = str(values['_id'])
        return values

    def change_status(self, new_status: str):
        try:
            status = InvitationStatus[new_status]
            self.lastSent = datetime.now(ZoneInfo('UTC'))
            self.inviteStatus = status
        except KeyError:
            raise ValueError(f'{new_status} is not a valid status')

    def toJson(self):
        data_json = self.model_dump(by_alias=True)

        if data_json.get('createdAt') != None:
            data_json["createdAt"] = str(self.createdAt)

        if data_json.get('lastSent') != None:
            data_json["lastSent"] = str(self.lastSent)

        if data_json.get('censusUser') != None:
            data_json["censusUser"] = self.censusUser.model_dump()

        if data_json.get('type') != None:
            data_json["type"] = self.type.value

        if data_json.get('inviteStatus') != None:
            data_json["inviteStatus"] = self.inviteStatus.value

        return data_json
