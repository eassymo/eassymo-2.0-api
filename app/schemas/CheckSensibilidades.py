from typing import Optional, Any, List
from pydantic import BaseModel, Field


class VehiculoInput(BaseModel):
    fabricante: str = Field(..., min_length=1)
    modelo: str = Field(..., min_length=1)
    ano: int = Field(...)
    version: Optional[str] = None
    motor: Optional[str] = None
    trim: Optional[str] = None


class ParteInput(BaseModel):
    tipoParteId: int = Field(...)
    tipoParteSensibleMotor: Optional[bool] = None
    tipoParteSensiblePosicion: Optional[bool] = None
    tipoParteSensibleRin: Optional[bool] = None
    tipoSensibleAnillosMotor: Optional[bool] = None


class CheckSensibilidadesRequest(BaseModel):
    vehiculo: VehiculoInput
    parte: ParteInput


class OptionItem(BaseModel):
    label: str
    value: Any = None


class SensibilidadItem(BaseModel):
    defaultLabel: str
    options: Optional[List[OptionItem]] = None
    dataType: Optional[str] = None
    optional: Optional[bool] = None
    valueKey: Optional[Any] = None
