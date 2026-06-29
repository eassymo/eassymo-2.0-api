from typing import List

from sqlalchemy.orm import Session, joinedload

from models import Categorias


class CategoriasRepository:

    @staticmethod
    def find_all_with_subcategorias(mysql_db: Session) -> List[Categorias]:
        return (
            mysql_db.query(Categorias)
            .options(joinedload(Categorias.subcategorias))
            .order_by(Categorias.CategoriaDescripcion.asc())
            .all()
        )
