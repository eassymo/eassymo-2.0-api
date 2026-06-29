from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo


class PhotoSchema(BaseModel):
    group_id: Optional[str] = Field(default="",
                                    description="id of the group that the user belongs to")
    userId: str = Field(description="id of the user that uploaded this")
    url: str = Field(description="Address")
    createdAt = Optional[datetime] = Field(
        default=datetime.now(ZoneInfo('UTC')))
    fileName: str = Field(description="File name")
