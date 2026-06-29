from pydantic import BaseModel, Field

class StandarizedVehicles(BaseModel):
    VehiculoInternalId: int
    VehicleId: int
    BaseId: int
    VehiculoDescripcion: str
    VehiculoFabricante: str
    VehiculoModelo: str
    VehiculoSubModelo: str
    VehiculoAno: int
    VehiculoTipo: str
    VehiculoComentarios: str
    nonAcesVehicle: bool = Field(False)

    def toJson(self):
        return self.model_dump()