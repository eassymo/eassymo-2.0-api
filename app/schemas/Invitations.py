from pydantic import BaseModel, Field
from enum import Enum
from app.schemas.Census import CensusSchema

class InvitationStatus(Enum):
    SENT=1
    REJECTED=2
    ACCEPTED=3

class InvitationType(Enum):
    WHATSAPP=1
    EMAIL=2
    SMS=3

class InvitationsSchema(BaseModel):
    user: str = Field(None, description="User that originated the invite")
    userName: str = Field(None, description="Name of user sending invite")
    inviteStatus: InvitationStatus = Field(InvitationStatus.SENT, description="Status of the invite")
    censusUser: CensusSchema = Field(None, description="user of the census that the invite was sent to")
    type: InvitationType = Field(None, description="Type of communication method used")
    finalContactInfo: str = Field(None, description="Final contact information used in the invite")
    censusId: str = Field(None, description="Id of the census user")