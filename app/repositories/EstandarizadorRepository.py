from typing import List

from sqlalchemy.orm import Session

from models import Unidadmedida, Tiposparte, Ensambladoras


class EstandarizadorRepository:

    @staticmethod
    def find_unidades_medida_by_tipo_parte(
        mysql_db: Session, id_tipo_parte: int
    ) -> List[Unidadmedida]:
        return (
            mysql_db.query(Unidadmedida)
            .join(Unidadmedida.tiposparte)
            .filter(Tiposparte.TipoParteId == id_tipo_parte)
            .distinct()
            .all()
        )

    @staticmethod
    def find_all_unidades_medida(mysql_db: Session) -> List[Unidadmedida]:
        return mysql_db.query(Unidadmedida).all()

    @staticmethod
    def find_all_ensambladoras(mysql_db: Session) -> List[Ensambladoras]:
        return (
            mysql_db.query(Ensambladoras)
            .order_by(Ensambladoras.EnsambladoraNombre.asc())
            .all()
        )
