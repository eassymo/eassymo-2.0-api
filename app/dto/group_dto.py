from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.schemas.GeoJsonLocation import GeoJson

class EditGroupDto(BaseModel):
    phone: Optional[str] = Field(None)
    whatsAppNumber: Optional[str] = Field(None)
    pos_whatsapp_intake: Optional[str] = Field(None)
    since: Optional[datetime] = Field(None)
    story: Optional[str] = Field(None)
    webPage: Optional[str] = Field(None)
    name: Optional[str] = Field(None)
    email: Optional[str] = Field(None)
    location: Optional[GeoJson] = Field(None)
    state: Optional[str] = Field(None)
    city: Optional[str] = Field(None)
    address: Optional[str] = Field(None)