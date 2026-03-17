from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config.database import get_mysql_db
from app.schemas.VehiculoPartesSearch import SearchPartesPaginatorRequest
from app.schemas.CheckSensibilidades import CheckSensibilidadesRequest
from app.services.VehiculoPartesService import search_partes_paginator
from app.services.VehiculoSensibilidadesService import check_sensibilidades

vehiculoRouter = APIRouter(prefix="/vehiculo", tags=["Vehiculo"])


@vehiculoRouter.post("/searchPartesPaginator")
def search_partes_paginator_endpoint(
    payload: SearchPartesPaginatorRequest,
    mysql_db: Session = Depends(get_mysql_db),
):
    if not payload.historicoBusqueda:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "INVALID_REQUEST"},
        )
    if not (payload.historicoBusqueda.criterio or payload.historicoBusqueda.usuario):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "INVALID_REQUEST"},
        )
    result = search_partes_paginator(mysql_db, payload)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@vehiculoRouter.post("/checkSensibilidades")
def check_sensibilidades_endpoint(
    payload: CheckSensibilidadesRequest,
    mysql_db: Session = Depends(get_mysql_db),
):
    if not payload.vehiculo:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "INVALID_REQUEST"},
        )
    if not payload.parte:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "INVALID_REQUEST"},
        )
    v = payload.vehiculo
    if not (v.fabricante and v.modelo and v.ano is not None):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "INVALID_REQUEST"},
        )
    try:
        result = check_sensibilidades(mysql_db, payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "GENERIC_ERROR"},
        )
