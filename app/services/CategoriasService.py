from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.repositories.CategoriasRepository import CategoriasRepository


def _subcategoria_to_item(sub) -> Dict[str, Any]:
    return {
        "subCategoriaId": int(sub.SubCategoriaId),
        "subCategoriaDescripcion": (sub.SubCategoriaDescripcion or "").strip(),
        "subCategoriaDescripcionEng": (sub.SubCategoriaDescripcionEng or "").strip() or None,
        "categoriaId": int(sub.CategoriaId),
        "activo": bool(sub.SubCategoriaActivo) if sub.SubCategoriaActivo is not None else True,
    }


def _categoria_to_item(categoria) -> Dict[str, Any]:
    subcategorias = sorted(
        [
            _subcategoria_to_item(sub)
            for sub in (categoria.subcategorias or [])
            if sub.SubCategoriaActivo is None or bool(sub.SubCategoriaActivo)
        ],
        key=lambda item: item["subCategoriaDescripcion"].lower(),
    )

    return {
        "categoriaId": int(categoria.CategoriaId),
        "categoriaDescripcion": (categoria.CategoriaDescripcion or "").strip(),
        "categoriaDescripcionEng": (categoria.CategoriaDescripcionEng or "").strip() or None,
        "activo": bool(categoria.CategoriaActivo) if categoria.CategoriaActivo is not None else True,
        "subcategorias": subcategorias,
    }


def get_all_categorias(mysql_db: Session) -> List[Dict[str, Any]]:
    categorias = CategoriasRepository.find_all_with_subcategorias(mysql_db)
    return [
        _categoria_to_item(item)
        for item in categorias
        if item.CategoriaActivo is None or bool(item.CategoriaActivo)
    ]


def build_default_sistemas_payload(mysql_db: Session) -> Dict[str, Any]:
    """All active categories fully selected; non-exclusive accepts any future category too."""
    categorias = get_all_categorias(mysql_db)
    return {
        "is_exclusive": False,
        "selected": [
            {
                "categoriaId": int(categoria["categoriaId"]),
                "subCategoriaIds": [],
            }
            for categoria in categorias
        ],
    }
