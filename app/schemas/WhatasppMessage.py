from pydantic import BaseModel, Field
from typing import Dict, Optional, List, Any

from datetime import datetime
from zoneinfo import ZoneInfo


class WhatsappTemplate(BaseModel):
    name: str = Field(..., description="Name of the template")
    variables: List[str] = Field(default=[], description="List of variables in order")
    language: Optional[str] = Field(
        default=None,
        description="WhatsApp template language code, e.g. es_MX",
    )


class WhatsappMessage(BaseModel):
    to: str = Field(..., description="Recipient phone")
    template: WhatsappTemplate = Field(..., description="template info")
    timestamp: Optional[datetime] = Field(datetime.now(ZoneInfo('UTC')))

    def toJson(self):
        data = self.model_dump()
        if self.timestamp != None:
            data["timestamp"] = str(self.timestamp)
        return data
