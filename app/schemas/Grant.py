from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

GrantPov = Literal["vendedor", "comprador", "ambos", "eassymo"]
GrantType = Literal["action", "visibility"]

# Fields a super admin may edit. `key`, `pov`, `type` and `implemented` come from code/seed.
EDITABLE_GRANT_FIELDS = frozenset({"name", "description", "area", "sort_order", "frame_refs", "active"})


class GrantSchema(BaseModel):
    key: str = Field(description="Immutable grant key checked by code, e.g. offers.accept")
    name: str
    description: str = ""
    area: str
    pov: GrantPov
    type: GrantType = "action"
    frame_refs: List[str] = Field(default_factory=list, description="Frame codes (frames collection) this grant controls")
    implemented: bool = True
    active: bool = True
    sort_order: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None
