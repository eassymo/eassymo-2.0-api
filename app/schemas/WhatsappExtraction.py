from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExtractionIntent(str, Enum):
    NEW_REQUEST = "new_request"
    UNKNOWN = "unknown"
    NOT_COMMERCIAL = "not_commercial"


class ExtractionVehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[str] = None
    engine: Optional[str] = None
    vin: Optional[str] = None

    @field_validator("make", "model", "year", "engine", "vin", mode="before")
    @classmethod
    def _stringify_optional_fields(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return str(value)


class ExtractionLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_id: str
    part_name: str
    quantity: int = Field(default=1, ge=1)
    unit: str = "pieza"
    position: Optional[str] = None
    raw: Optional[str] = None


class ExtractionUncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    reason: str


class ExtractionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    raw: str
    kind: str = "literal"


class WhatsappExtractionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    intent: ExtractionIntent
    vehicle: Optional[ExtractionVehicle] = None
    lines: List[ExtractionLine] = Field(default_factory=list)
    uncertainties: List[ExtractionUncertainty] = Field(default_factory=list)
    evidence: List[ExtractionEvidence] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
