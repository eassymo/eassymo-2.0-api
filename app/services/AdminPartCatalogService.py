from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.repositories.PartCatalogRepository import PartCatalogRepository


def _tag_to_item(tag) -> Dict[str, Any]:
    return {
        "categoriaId": tag.CategoriaId,
        "subCategoriaId": tag.SubCategoriaId,
        "tipoParteId": tag.TipoParteId,
        "tipoParteTagId": tag.TipoParteTagId,
        "tipoParteTagDescripcion": tag.TipoParteTagDescripcion or "",
    }


def _unit_to_item(unit) -> Dict[str, Any]:
    return {
        "unidadMedidaId": unit.UnidadMedidaId,
        "etiquetaDefecto": unit.etiquetadefecto or "",
        "clavei18n": unit.clavei18n or "",
    }


def _position_to_item(position) -> Dict[str, Any]:
    return {
        "posicionId": position.PosicionId,
        "posicionNombre": position.PosicionNombre or "",
        "clavei18n": position.clavei18n or "",
    }


def _part_type_to_item(part) -> Dict[str, Any]:
    return {
        "tipoParteId": part.TipoParteId,
        "tipoParteDescripcion": (part.TipoParteDescripcion or "").strip(),
        "categoriaId": part.CategoriaId,
        "subCategoriaId": part.SubCategoriaId,
    }


class AdminPartCatalogService:
    @staticmethod
    def list_part_types(
        mysql_db: Session,
        page: int = 1,
        page_size: int = 24,
    ) -> Dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        items, total = PartCatalogRepository.find_part_types_paginated(
            mysql_db, offset, page_size
        )
        return {
            "items": [_part_type_to_item(p) for p in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max((total + page_size - 1) // page_size, 1),
        }

    @staticmethod
    def list_part_tags(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
    ) -> Dict[str, Any]:
        tags = PartCatalogRepository.find_tags(
            mysql_db, categoria_id, sub_categoria_id, tipo_parte_id
        )
        return {"items": [_tag_to_item(t) for t in tags]}

    @staticmethod
    def list_measurement_units(
        mysql_db: Session,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        items, total = PartCatalogRepository.find_units_paginated(
            mysql_db, search, offset, page_size
        )
        return {
            "items": [_unit_to_item(u) for u in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max((total + page_size - 1) // page_size, 1),
        }

    @staticmethod
    def list_part_unit_links(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
    ) -> Dict[str, Any]:
        all_units = PartCatalogRepository.find_all_units(mysql_db)
        linked_ids = PartCatalogRepository.find_linked_unit_ids(
            mysql_db, categoria_id, sub_categoria_id, tipo_parte_id
        )
        return {
            "allUnits": [_unit_to_item(u) for u in all_units],
            "linkedUnitIds": linked_ids,
        }

    @staticmethod
    def list_positions(
        mysql_db: Session,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        items, total = PartCatalogRepository.find_positions_paginated(
            mysql_db, search, offset, page_size
        )
        return {
            "items": [_position_to_item(p) for p in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max((total + page_size - 1) // page_size, 1),
        }

    @staticmethod
    def list_part_position_links(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
    ) -> Dict[str, Any]:
        all_positions = PartCatalogRepository.find_all_positions(mysql_db)
        linked_ids = PartCatalogRepository.find_linked_position_ids(
            mysql_db, categoria_id, sub_categoria_id, tipo_parte_id
        )
        return {
            "allPositions": [_position_to_item(p) for p in all_positions],
            "linkedPositionIds": linked_ids,
        }
