from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class EditGroupDto(BaseModel):
    phone: Optional[str] = Field(None)
    whatsAppNumber: Optional[str] = Field(None)
    since: Optional[datetime] = Field(None)
    story: Optional[str] = Field(None)
    webPage: Optional[str] = Field(None)
    name: Optional[str] = Field(None)
    email: Optional[str] = Field(None)