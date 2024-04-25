from pydantic import BaseModel, Field
from typing import List

class ListsSchema(BaseModel):
    group_id:str = Field(description="group owner of the list")
    user_uid: str = Field(description="user owner of the list")
    groups: List[str] = Field(description="Groups belonging to this list")
    name: str = Field(description="Name of the list")
    is_priority: bool = Field(description="this field determines if it is a priority")