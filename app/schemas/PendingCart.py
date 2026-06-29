from pydantic import BaseModel, Field
from typing import List, Optional
from bson import ObjectId


class PendingCartPart(BaseModel):
    tipoParteId: str
    tipoParteDescripcion: str
    tipoParteSensibleMotor: Optional[bool] = None
    tipoParteSensiblePosicion: Optional[bool] = None
    tipoParteSensibleRin: Optional[bool] = None
    tipoSensibleAnillosMotor: Optional[bool] = None
    tipoParteActivo: bool
    categoriaId: int
    subCategoriaId: int
    tags: Optional[list] = None
    comments: Optional[str] = None
    position: Optional[str] = None
    unitOfMeasure: Optional[str] = None
    amount: Optional[int] = None
    photos: Optional[List[str]] = None
    listUid: Optional[str] = None


class SavePendingCartRequest(BaseModel):
    user_uid: str
    group_id: str
    vehicle_id: Optional[str] = None
    part_list: List[PendingCartPart] = Field(default_factory=list)
