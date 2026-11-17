from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RolesSchema(BaseModel):
    description: str = Field(None, description="This is the description of the role, will be displayed in the FE list")
    value: str = Field(None, description="Value we get from the table")
    display: bool = Field(True, description="Determines if will be displayed")
    entityType: str = Field(None, description="Determines the type of bussiness")
    # Grants model (phase 1)
    grants: List[str] = Field(default_factory=list, description="Grant keys this role gives")
    pov: Optional[str] = Field(None, description="vendedor | comprador | ambos")
    entity_types: List[str] = Field(default_factory=list, description="Group types this role fits; empty = all")
    function: Optional[str] = Field(None, description="admin, vendedor, gestor, almacenista, repartidor, mecanico, comprador, legacy")
    assignable_by_group_admins: bool = Field(False)
    active: bool = Field(True)
    is_system: bool = Field(False)
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None

    def toJson(self):
        data = self.model_dump()

        return data
