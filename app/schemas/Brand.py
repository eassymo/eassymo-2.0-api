from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo


class Brand(BaseModel):
    label: str = Field(
        description="This is the label that will be injected in the autocomplete items")
    user_uid: str = Field(description="Creator of this label")
    created_at: Optional[datetime] = Field(
        default=datetime.now(ZoneInfo('utc')))
