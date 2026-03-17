from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config.database import get_mysql_db
from app.services.EstandarizadorService import get_unidades_medida_by_parte

estandarizadorRouter = APIRouter(prefix="/estandarizador", tags=["Estandarizador"])


@estandarizadorRouter.get("/findUnidadesMedidaByParte")
def find_unidades_medida_by_parte(
    idTipoParte: int | None = Query(None, description="Part type ID"),
    mysql_db: Session = Depends(get_mysql_db),
):
    if idTipoParte is None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "INVALID_REQUEST"},
        )
    try:
        result = get_unidades_medida_by_parte(mysql_db, idTipoParte)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"success": False, "code": "GENERIC_ERROR"},
        )
