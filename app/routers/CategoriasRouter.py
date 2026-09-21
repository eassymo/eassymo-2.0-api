from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config.database import get_mysql_db
from app.services.CategoriasService import get_all_categorias
from app.utils.ResponseUtils import get_successful_response, error_json_response

categoriasRouter = APIRouter(prefix="/categorias", tags=["Categorias"])


@categoriasRouter.get("")
def list_categorias(mysql_db: Session = Depends(get_mysql_db)):
    try:
        result = get_all_categorias(mysql_db)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(result)),
        )
    except HTTPException:
        raise
    except Exception as e:
        return error_json_response(e)
