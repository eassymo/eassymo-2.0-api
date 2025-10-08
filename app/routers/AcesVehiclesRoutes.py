from fastapi.responses import JSONResponse
from fastapi import APIRouter, status, Query, HTTPException, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.services.AcesVehiclesService import AcesVehiclesService
from app.config.database import get_mysql_db

AcesVehiclesRouter = APIRouter(prefix="/AcesVehicles")


@AcesVehiclesRouter.get("/", tags=["Aces Vehicles"])
def find(
    search_argument: Optional[str] = Query(None, title="search_argument"),
    year: Optional[str] = Query(None, title="year"),
    mysql_db: Session = Depends(get_mysql_db)
) -> JSONResponse:
    try:
        if not search_argument:
            return get_unsuccessful_response(Exception("Please provide a search argument"))

        vehicles = AcesVehiclesService.find_aces_vehicles(
            mysql_db, search_argument, year)

        vehicles_data = []
        for vehicle in vehicles:
            vehicle_dict = {
                "VehiculoInternalId": vehicle.VehiculoInternalId,
                "VehicleId": vehicle.VehicleId,
                "BaseId": vehicle.BaseId,
                "VehiculoDescripcion": vehicle.VehiculoDescripcion,
                "VehiculoFabricante": vehicle.VehiculoFabricante,
                "VehiculoModelo": vehicle.VehiculoModelo,
                "VehiculoSubModelo": vehicle.VehiculoSubModelo,
                "VehiculoAno": vehicle.VehiculoAno,
                "VehiculoTipo": vehicle.VehiculoTipo,
                "VehiculoComentarios": vehicle.VehiculoComentarios,
            }
            vehicles_data.append(vehicle_dict)

        return get_successful_response(vehicles_data)

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )
