from pydantic import BaseModel, Field
from typing import List

class Location(BaseModel):
    type: str
    coordinates: List[float]