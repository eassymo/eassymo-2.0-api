from typing import Dict, Any, List

from sqlalchemy.orm import Session

from app.repositories.EstandarizadorRepository import EstandarizadorRepository
from app.repositories.NonAcesVehiclesRepository import find_distinct_makes
from app.utils.armadora_names import (
    format_armadora_display_name,
    normalize_armadora_name,
    pick_preferred_ensambladora_item,
)
from models import Ensambladoras


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


def _ensambladora_to_item(e: Ensambladoras) -> Dict[str, Any]:
    return {
        "ensambladoraId": e.EnsambladoraId,
        "ensambladoraNombre": format_armadora_display_name(e.EnsambladoraNombre or ""),
        "ensambladoraDescr": format_armadora_display_name(e.EnsambladoraDescr or ""),
        "ensambladoraImagen": e.EnsambladoraImagen_GXI or "",
    }


def get_all_ensambladoras(mysql_db: Session) -> Dict[str, Any]:
    sql_lst = EstandarizadorRepository.find_all_ensambladoras(mysql_db)
    mongo_makes = find_distinct_makes()

    sql_by_key: Dict[str, Dict[str, Any]] = {}
    for ensambladora in sql_lst:
        item = _ensambladora_to_item(ensambladora)
        key = normalize_armadora_name(item["ensambladoraNombre"])
        if not key:
            continue
        if key in sql_by_key:
            sql_by_key[key] = pick_preferred_ensambladora_item(sql_by_key[key], item)
        else:
            sql_by_key[key] = item

    seen: set[str] = set(sql_by_key.keys())
    merged: List[Dict[str, Any]] = list(sql_by_key.values())

    for make in mongo_makes:
        name = format_armadora_display_name(make)
        key = normalize_armadora_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "ensambladoraId": 0,
                "ensambladoraNombre": name,
                "ensambladoraDescr": "",
                "ensambladoraImagen": "",
            }
        )

    merged.sort(
        key=lambda item: normalize_armadora_name(item["ensambladoraNombre"])
    )

    return {
        "success": True,
        "lstEnsambladoras": merged,
    }
