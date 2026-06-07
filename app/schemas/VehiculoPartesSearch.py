from typing import Optional, List, Any
from pydantic import BaseModel, Field


class HistoricoBusquedaInput(BaseModel):
    criterio: str = Field(..., min_length=1)
    usuario: Optional[str] = Field(None)
    details: Optional[List[Any]] = Field(default_factory=list)


class SearchPartesPaginatorRequest(BaseModel):
    historicoBusqueda: HistoricoBusquedaInput
    page: int = Field(default=0, ge=0)
    itemsPerPage: int = Field(default=100, ge=1, le=500)


class TagOut(BaseModel):
    tipoParteTagDescripcion: str


class CategoriaOut(BaseModel):
    categoriaId: int
    categoriaDescripcion: str


class SubCategoriaOut(BaseModel):
    subCategoriaId: int
    subCategoriaDescripcion: str


class ParteItemOut(BaseModel):
    tipoParteId: int
    tipoParteDescripcion: str
    tipoParteSensibleMotor: bool
    tipoParteSensiblePosicion: bool
    tipoParteSensibleRin: bool
    tipoSensibleAnillosMotor: bool
    categoriaId: int
    subCategoriaId: int
    tags: List[TagOut]
    categoria: CategoriaOut
    subCategoria: SubCategoriaOut
    countVehiclesCompat: int = 0


class DetailPartesOut(BaseModel):
    partes: List[ParteItemOut]


class HistoricoBusquedaOutput(BaseModel):
    criterio: str
    usuario: Optional[str]
    details: List[DetailPartesOut]


class SearchPartesPaginatorSuccessResponse(BaseModel):
    success: bool = True
    historicoBusqueda: HistoricoBusquedaOutput
    pages: int
    count: int


class SearchPartesPaginatorErrorResponse(BaseModel):
    success: bool = False
    code: str
