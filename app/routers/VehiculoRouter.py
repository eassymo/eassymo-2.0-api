import os

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.config.database import get_mysql_db
from app.schemas.VehiculoPartesSearch import SearchPartesPaginatorRequest
from app.schemas.CheckSensibilidades import CheckSensibilidadesRequest
from app.schemas.VehiculoVehiclesByIds import VehiclesByIdsRequest
from app.services.VehiculoPartesService import search_partes_paginator
from app.services.VehiculoSensibilidadesService import check_sensibilidades
from app.repositories.VehiculoSensibilidadesRepository import VehiculoSensibilidadesRepository
from app.services import GroupCarService
from app.utils import TypeUtilities as typeUtilities
from app.utils.ResponseUtils import get_successful_response, error_json_response

vehiculoRouter = APIRouter(prefix="/vehiculo", tags=["Vehiculo"])


@vehiculoRouter.post("/searchPartesPaginator")
def search_partes_paginator_endpoint(
    payload: SearchPartesPaginatorRequest,
    mysql_db: Session = Depends(get_mysql_db),
):
    if not payload.historicoBusqueda:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_REQUEST")
    if not (payload.historicoBusqueda.criterio or payload.historicoBusqueda.usuario):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_REQUEST")
    result = search_partes_paginator(mysql_db, payload)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@vehiculoRouter.post("/checkSensibilidades")
def check_sensibilidades_endpoint(
    payload: CheckSensibilidadesRequest,
    mysql_db: Session = Depends(get_mysql_db),
):
    if not payload.vehiculo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_REQUEST")
    if not payload.parte:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_REQUEST")
    v = payload.vehiculo
    if not (v.fabricante and v.modelo and v.ano is not None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_REQUEST")
    try:
        result = check_sensibilidades(mysql_db, payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except HTTPException:
        raise
    except Exception as e:
        return error_json_response(e)


@vehiculoRouter.get("/findAllVersiones")
def find_all_versiones(
    vehiculoFabricante: str = Query(...),
    vehiculoModelo: str = Query(...),
    vehiculoAno: int = Query(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        country_id = int(os.getenv("COUNTRY_ID", "484"))
        rows = VehiculoSensibilidadesRepository.find_all_versiones(
            mysql_db, vehiculoFabricante, vehiculoModelo, vehiculoAno, country_id
        )
        data = [
            {"vehiculoSubModelo": r.VehiculoSubModelo, "vehiculoMotorId": r.VehiculoMotorId}
            for r in rows
        ]
        return JSONResponse(status_code=status.HTTP_200_OK, content={"data": data})
    except HTTPException:
        raise
    except Exception as e:
        return error_json_response(e)


@vehiculoRouter.get("/findAllMotorDesc")
def find_all_motor_desc(
    vehiculoFabricante: str = Query(...),
    vehiculoModelo: str = Query(...),
    vehiculoAno: int = Query(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        country_id = int(os.getenv("COUNTRY_ID", "484"))
        rows = VehiculoSensibilidadesRepository.find_all_motor_desc(
            mysql_db, vehiculoFabricante, vehiculoModelo, vehiculoAno, country_id
        )
        data = [
            {"vehiculoMotorDescripcion": r.VehiculoMotorDescripcion, "vehiculoMotorId": r.VehiculoMotorId}
            for r in rows
        ]
        return JSONResponse(status_code=status.HTTP_200_OK, content={"data": data})
    except HTTPException:
        raise
    except Exception as e:
        return error_json_response(e)


@vehiculoRouter.post("/vehicles-by-ids")
def vehicles_by_ids(payload = Body(...)):
    try:
        vehicles = GroupCarService.find_by_ids(payload.get("vehicleIds"))
        formatted = typeUtilities.parse_json(vehicles)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(formatted)),
        )
    except HTTPException:
        raise
    except Exception as e:
        return error_json_response(e)
