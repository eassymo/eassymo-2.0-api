from pydantic import BaseModel, Field
from typing import List

class GeoJson(BaseModel):
    type: str
    coordinates: List[float]