from typing import Dict, Any, List

from sqlalchemy.orm import Session

from app.repositories.EstandarizadorRepository import EstandarizadorRepository


def _unidad_to_item(u) -> Dict[str, Any]:
    return {
        "unidadMedidaId": u.UnidadMedidaId,
        "etiquetaDefecto": u.etiquetadefecto or "",
        "clavei18n": u.clavei18n or "",
    }


def get_unidades_medida_by_parte(
    mysql_db: Session, id_tipo_parte: int
) -> Dict[str, Any]:
    lst = EstandarizadorRepository.find_unidades_medida_by_tipo_parte(
        mysql_db, id_tipo_parte
    )
    if not lst:
        lst = EstandarizadorRepository.find_all_unidades_medida(mysql_db)
    lst_unidades: List[Dict[str, Any]] = [_unidad_to_item(u) for u in lst]
    return {"success": True, "lstUnidadesMedida": lst_unidades}
