from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from pydantic import BaseModel, Field
from zoneinfo import ZoneInfo


class ArmadoraSelection(BaseModel):
    ensambladoraId: int
    ensambladoraNombre: str


class ArmadorasConfig(BaseModel):
    is_exclusive: bool = False
    selected: List[ArmadoraSelection] = Field(default_factory=list)


class ArmadorasConfigUpdate(BaseModel):
    is_exclusive: bool = False
    selected: List[ArmadoraSelection] = Field(default_factory=list)


class SistemasSelection(BaseModel):
    categoriaId: int
    subCategoriaIds: List[int] = Field(default_factory=list)


class SistemasConfig(BaseModel):
    is_exclusive: bool = False
    selected: List[SistemasSelection] = Field(default_factory=list)


class SistemasConfigUpdate(BaseModel):
    is_exclusive: bool = False
    selected: List[SistemasSelection] = Field(default_factory=list)


class GroupConfig(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    group_id: str
    armadoras: ArmadorasConfig = Field(default_factory=ArmadorasConfig)
    sistemas: SistemasConfig = Field(default_factory=SistemasConfig)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True

    @classmethod
    def convert_object_id(cls, values):
        if isinstance(values, dict) and "_id" in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def toJson(self):
        data = self.model_dump(by_alias=True)
        if data.get("created_at"):
            data["created_at"] = self.created_at.isoformat() if self.created_at else None
        if data.get("updated_at"):
            data["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return data


class ArmadoraCompatibilityRequest(BaseModel):
    vehicle_maker: Optional[str] = None
    group_ids: List[str] = Field(default_factory=list)


class ExcludedArmadoraGroup(BaseModel):
    group_id: str
    reason: str
    selected_armadoras: List[ArmadoraSelection] = Field(default_factory=list)


class ArmadoraCompatibilityResponse(BaseModel):
    compatible: List[str] = Field(default_factory=list)
    excluded: List[ExcludedArmadoraGroup] = Field(default_factory=list)


class PartCategoryRequirement(BaseModel):
    categoria_id: int
    sub_categoria_id: int


class SistemasCompatibilityRequest(BaseModel):
    group_ids: List[str] = Field(default_factory=list)
    part_categories: List[PartCategoryRequirement] = Field(default_factory=list)


class ExcludedSistemasGroup(BaseModel):
    group_id: str
    reason: str
    selected_sistemas: List[SistemasSelection] = Field(default_factory=list)


class SistemasCompatibilityResponse(BaseModel):
    compatible: List[str] = Field(default_factory=list)
    excluded: List[ExcludedSistemasGroup] = Field(default_factory=list)


def default_group_config(group_id: str) -> GroupConfig:
    now = datetime.now(ZoneInfo("UTC"))
    return GroupConfig(
        group_id=group_id,
        armadoras=ArmadorasConfig(),
        sistemas=SistemasConfig(),
        created_at=now,
        updated_at=now,
    )
