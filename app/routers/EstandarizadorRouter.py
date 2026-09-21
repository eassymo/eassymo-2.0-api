from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config.database import get_mysql_db
from app.services.EstandarizadorService import (
    get_unidades_medida_by_parte,
    get_all_ensambladoras,
    get_all_unidades_medida,
    get_all_posiciones,
)
from app.utils.ResponseUtils import error_json_response

estandarizadorRouter = APIRouter(prefix="/estandarizador", tags=["Estandarizador"])


@estandarizadorRouter.get("/findUnidadesMedidaByParte")
def find_unidades_medida_by_parte(
    idTipoParte: int | None = Query(None, description="Part type ID"),
    mysql_db: Session = Depends(get_mysql_db),
):
    if idTipoParte is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_REQUEST")
    try:
        result = get_unidades_medida_by_parte(mysql_db, idTipoParte)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except HTTPException:
        raise
    except Exception as e:
        return error_json_response(e)


@estandarizadorRouter.get("/findAllEnsambladoras")
def find_all_ensambladoras(
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        result = get_all_ensambladoras(mysql_db)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except HTTPException:
        raise
    except Exception as e:
        return error_json_response(e)


@estandarizadorRouter.get("/findAllUnidadesMedida")
def find_all_unidades_medida(
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        result = get_all_unidades_medida(mysql_db)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except HTTPException:
        raise
    except Exception as e:
        return error_json_response(e)


@estandarizadorRouter.get("/findAllPosiciones")
def find_all_posiciones(
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        result = get_all_posiciones(mysql_db)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except HTTPException:
        raise
    except Exception as e:
        return error_json_response(e)
