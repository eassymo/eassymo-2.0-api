from typing import Any, List, Literal, Optional

from pydantic import BaseModel


class PreviewIn(BaseModel):
    """What the review sheet would send, to count each part's audience before creating it."""
    group_id: str
    vehicle_id: str
    part_list: List[Any]
    subscribed_sellers: List[str]
    subscribed_followers: List[str] = []
    commissioner_group: Optional[str] = None


class ReachSettingsPatch(BaseModel):
    """Admin edit of the global limits or one store's override. Every field is optional."""
    wide_threshold: Optional[int] = None
    wide_per_day: Optional[int] = None
    capped_max: Optional[int] = None
    enforcement: Optional[Literal["shadow", "enforce"]] = None
