from typing import List
from pydantic import BaseModel, Field


class VehiclesByIdsRequest(BaseModel):
    vehicleIds: List[str] = Field(
        ...,
        description="MongoDB ObjectIds of GroupCars (same as PartRequest.vehicleId)",
    )
