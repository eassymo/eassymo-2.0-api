import math
from typing import Dict, Any, List

from sqlalchemy.orm import Session

from app.repositories.VehiculoPartesRepository import VehiculoPartesRepository
from app.utils.search_partes import prepare_fulltext_variant_groups
from app.schemas.VehiculoPartesSearch import (
    SearchPartesPaginatorRequest,
    ParteItemOut,
    TagOut,
    CategoriaOut,
    SubCategoriaOut,
    DetailPartesOut,
    HistoricoBusquedaOutput,
)


def _parte_to_item(tipo_parte) -> Dict[str, Any]:
    cat = tipo_parte.subcategorias.categorias
    subcat = tipo_parte.subcategorias
    tags = [
        TagOut(tipoParteTagDescripcion=t.TipoParteTagDescripcion or "")
        for t in (tipo_parte.tipospartetag or [])
    ]
    return ParteItemOut(
        tipoParteId=tipo_parte.TipoParteId,
        tipoParteDescripcion=tipo_parte.TipoParteDescripcion or "",
        tipoParteSensibleMotor=bool(tipo_parte.TipoParteSensibleMotor),
        tipoParteSensiblePosicion=bool(tipo_parte.TipoParteSensiblePosicion),
        tipoParteSensibleRin=bool(tipo_parte.TipoParteSensibleRin),
        tipoSensibleAnillosMotor=bool(tipo_parte.TipoSensibleAnillosMotor),
        categoriaId=tipo_parte.CategoriaId,
        subCategoriaId=tipo_parte.SubCategoriaId,
        tags=tags,
        categoria=CategoriaOut(categoriaId=cat.CategoriaId, categoriaDescripcion=cat.CategoriaDescripcion or ""),
        subCategoria=SubCategoriaOut(
            subCategoriaId=subcat.SubCategoriaId,
            subCategoriaDescripcion=subcat.SubCategoriaDescripcion or "",
        ),
        countVehiclesCompat=0,
    )


def search_partes_paginator(
    mysql_db: Session, payload: SearchPartesPaginatorRequest
) -> Dict[str, Any]:
    variant_groups = prepare_fulltext_variant_groups(payload.historicoBusqueda.criterio)
    if not variant_groups:
        total = 0
        partes: List[ParteItemOut] = []
    else:
        total = VehiculoPartesRepository.count_by_fulltext_variants(
            mysql_db, variant_groups
        )
        offset = payload.page * payload.itemsPerPage
        rows = VehiculoPartesRepository.find_partes_paginated_fulltext_variants(
            mysql_db, variant_groups, offset, payload.itemsPerPage
        )
        partes = [_parte_to_item(r) for r in rows]

    pages = math.ceil(total / payload.itemsPerPage) if total else 0
    historico = HistoricoBusquedaOutput(
        criterio=payload.historicoBusqueda.criterio,
        usuario=payload.historicoBusqueda.usuario,
        details=[DetailPartesOut(partes=partes)],
    )
    return {
        "success": True,
        "historicoBusqueda": historico.model_dump(),
        "pages": pages,
        "count": total,
    }
