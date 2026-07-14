from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import (
    Posiciones,
    Tiposparte,
    Tipospartetag,
    Unidadmedida,
    t_tiposparteposicion,
    t_tiposparteunidadmedida,
)


class PartCatalogRepository:
  # ── Tags / synonyms ───────────────────────────────────────────────────────

    @staticmethod
    def find_tags(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
    ) -> List[Tipospartetag]:
        return (
            mysql_db.query(Tipospartetag)
            .filter(
                Tipospartetag.CategoriaId == categoria_id,
                Tipospartetag.SubCategoriaId == sub_categoria_id,
                Tipospartetag.TipoParteId == tipo_parte_id,
            )
            .order_by(Tipospartetag.TipoParteTagId.asc())
            .all()
        )

    @staticmethod
    def _next_tag_id(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
    ) -> int:
        max_id = (
            mysql_db.query(func.max(Tipospartetag.TipoParteTagId))
            .filter(
                Tipospartetag.CategoriaId == categoria_id,
                Tipospartetag.SubCategoriaId == sub_categoria_id,
                Tipospartetag.TipoParteId == tipo_parte_id,
            )
            .scalar()
        )
        return int(max_id or 0) + 1

    @staticmethod
    def _tag_description_exists(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
        description: str,
        exclude_tag_id: Optional[int] = None,
    ) -> bool:
        q = mysql_db.query(Tipospartetag).filter(
            Tipospartetag.CategoriaId == categoria_id,
            Tipospartetag.SubCategoriaId == sub_categoria_id,
            Tipospartetag.TipoParteId == tipo_parte_id,
            func.lower(Tipospartetag.TipoParteTagDescripcion) == description.strip().lower(),
        )
        if exclude_tag_id is not None:
            q = q.filter(Tipospartetag.TipoParteTagId != exclude_tag_id)
        return q.first() is not None

    @staticmethod
    def create_tag(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
        description: str,
    ) -> Tipospartetag:
        desc = description.strip()
        if PartCatalogRepository._tag_description_exists(
            mysql_db, categoria_id, sub_categoria_id, tipo_parte_id, desc
        ):
            raise ValueError("DUPLICATE_TAG")

        tag = Tipospartetag(
            CategoriaId=categoria_id,
            SubCategoriaId=sub_categoria_id,
            TipoParteId=tipo_parte_id,
            TipoParteTagId=PartCatalogRepository._next_tag_id(
                mysql_db, categoria_id, sub_categoria_id, tipo_parte_id
            ),
            TipoParteTagDescripcion=desc[:100],
        )
        mysql_db.add(tag)
        mysql_db.commit()
        mysql_db.refresh(tag)
        return tag

    @staticmethod
    def update_tag(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
        tipo_parte_tag_id: int,
        description: str,
    ) -> Optional[Tipospartetag]:
        tag = (
            mysql_db.query(Tipospartetag)
            .filter(
                Tipospartetag.CategoriaId == categoria_id,
                Tipospartetag.SubCategoriaId == sub_categoria_id,
                Tipospartetag.TipoParteId == tipo_parte_id,
                Tipospartetag.TipoParteTagId == tipo_parte_tag_id,
            )
            .first()
        )
        if not tag:
            return None

        desc = description.strip()
        if PartCatalogRepository._tag_description_exists(
            mysql_db,
            categoria_id,
            sub_categoria_id,
            tipo_parte_id,
            desc,
            exclude_tag_id=tipo_parte_tag_id,
        ):
            raise ValueError("DUPLICATE_TAG")

        tag.TipoParteTagDescripcion = desc[:100]
        mysql_db.commit()
        mysql_db.refresh(tag)
        return tag

    @staticmethod
    def delete_tag(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
        tipo_parte_tag_id: int,
    ) -> bool:
        deleted = (
            mysql_db.query(Tipospartetag)
            .filter(
                Tipospartetag.CategoriaId == categoria_id,
                Tipospartetag.SubCategoriaId == sub_categoria_id,
                Tipospartetag.TipoParteId == tipo_parte_id,
                Tipospartetag.TipoParteTagId == tipo_parte_tag_id,
            )
            .delete(synchronize_session=False)
        )
        mysql_db.commit()
        return deleted > 0

    # ── Part types (browse) ───────────────────────────────────────────────────

    @staticmethod
    def find_part_types_paginated(
        mysql_db: Session,
        offset: int,
        limit: int,
    ) -> Tuple[List[Tiposparte], int]:
        q = mysql_db.query(Tiposparte).filter(Tiposparte.TipoParteActivo == 1)
        total = q.count()
        items = (
            q.order_by(Tiposparte.TipoParteDescripcion.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    # ── Measurement units ─────────────────────────────────────────────────────

    @staticmethod
    def find_all_units(mysql_db: Session) -> List[Unidadmedida]:
        return (
            mysql_db.query(Unidadmedida)
            .order_by(Unidadmedida.etiquetadefecto.asc())
            .all()
        )

    @staticmethod
    def find_units_paginated(
        mysql_db: Session,
        search: Optional[str],
        offset: int,
        limit: int,
    ) -> Tuple[List[Unidadmedida], int]:
        q = mysql_db.query(Unidadmedida)
        if search:
            pattern = f"%{search.strip()}%"
            q = q.filter(
                Unidadmedida.etiquetadefecto.ilike(pattern)
                | Unidadmedida.clavei18n.ilike(pattern)
            )
        total = q.count()
        items = (
            q.order_by(Unidadmedida.etiquetadefecto.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    @staticmethod
    def create_unit(
        mysql_db: Session,
        etiqueta_defecto: str,
        clave_i18n: Optional[str] = None,
    ) -> Unidadmedida:
        max_id = mysql_db.query(func.max(Unidadmedida.UnidadMedidaId)).scalar()
        unit = Unidadmedida(
            UnidadMedidaId=int(max_id or 0) + 1,
            etiquetadefecto=etiqueta_defecto.strip(),
            clavei18n=(clave_i18n or "").strip() or None,
        )
        mysql_db.add(unit)
        mysql_db.commit()
        mysql_db.refresh(unit)
        return unit

    @staticmethod
    def update_unit(
        mysql_db: Session,
        unit_id: int,
        etiqueta_defecto: str,
        clave_i18n: Optional[str] = None,
    ) -> Optional[Unidadmedida]:
        unit = (
            mysql_db.query(Unidadmedida)
            .filter(Unidadmedida.UnidadMedidaId == unit_id)
            .first()
        )
        if not unit:
            return None
        unit.etiquetadefecto = etiqueta_defecto.strip()
        unit.clavei18n = (clave_i18n or "").strip() or None
        mysql_db.commit()
        mysql_db.refresh(unit)
        return unit

    @staticmethod
    def delete_unit(mysql_db: Session, unit_id: int) -> bool:
        unit = (
            mysql_db.query(Unidadmedida)
            .filter(Unidadmedida.UnidadMedidaId == unit_id)
            .first()
        )
        if not unit:
            return False
        try:
            mysql_db.delete(unit)
            mysql_db.commit()
            return True
        except IntegrityError:
            mysql_db.rollback()
            raise ValueError("UNIT_IN_USE")

    @staticmethod
    def find_linked_unit_ids(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
    ) -> List[int]:
        rows = mysql_db.execute(
            select(t_tiposparteunidadmedida.c.UnidadMedidaId).where(
                t_tiposparteunidadmedida.c.CategoriaId == categoria_id,
                t_tiposparteunidadmedida.c.SubCategoriaId == sub_categoria_id,
                t_tiposparteunidadmedida.c.TipoParteId == tipo_parte_id,
            )
        ).all()
        return [int(r[0]) for r in rows]

    @staticmethod
    def link_unit(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
        unit_id: int,
    ) -> None:
        exists = mysql_db.execute(
            select(t_tiposparteunidadmedida.c.UnidadMedidaId).where(
                t_tiposparteunidadmedida.c.CategoriaId == categoria_id,
                t_tiposparteunidadmedida.c.SubCategoriaId == sub_categoria_id,
                t_tiposparteunidadmedida.c.TipoParteId == tipo_parte_id,
                t_tiposparteunidadmedida.c.UnidadMedidaId == unit_id,
            )
        ).first()
        if exists:
            return
        mysql_db.execute(
            insert(t_tiposparteunidadmedida).values(
                CategoriaId=categoria_id,
                SubCategoriaId=sub_categoria_id,
                TipoParteId=tipo_parte_id,
                UnidadMedidaId=unit_id,
            )
        )
        mysql_db.commit()

    @staticmethod
    def unlink_unit(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
        unit_id: int,
    ) -> bool:
        result = mysql_db.execute(
            delete(t_tiposparteunidadmedida).where(
                t_tiposparteunidadmedida.c.CategoriaId == categoria_id,
                t_tiposparteunidadmedida.c.SubCategoriaId == sub_categoria_id,
                t_tiposparteunidadmedida.c.TipoParteId == tipo_parte_id,
                t_tiposparteunidadmedida.c.UnidadMedidaId == unit_id,
            )
        )
        mysql_db.commit()
        return result.rowcount > 0

    # ── Positions ─────────────────────────────────────────────────────────────

    @staticmethod
    def find_all_positions(mysql_db: Session) -> List[Posiciones]:
        return (
            mysql_db.query(Posiciones)
            .order_by(Posiciones.PosicionNombre.asc())
            .all()
        )

    @staticmethod
    def find_positions_paginated(
        mysql_db: Session,
        search: Optional[str],
        offset: int,
        limit: int,
    ) -> Tuple[List[Posiciones], int]:
        q = mysql_db.query(Posiciones)
        if search:
            pattern = f"%{search.strip()}%"
            q = q.filter(
                Posiciones.PosicionNombre.ilike(pattern)
                | Posiciones.clavei18n.ilike(pattern)
            )
        total = q.count()
        items = (
            q.order_by(Posiciones.PosicionNombre.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    @staticmethod
    def create_position(
        mysql_db: Session,
        posicion_nombre: str,
        clave_i18n: Optional[str] = None,
    ) -> Posiciones:
        max_id = mysql_db.query(func.max(Posiciones.PosicionId)).scalar()
        position = Posiciones(
            PosicionId=int(max_id or 0) + 1,
            PosicionNombre=posicion_nombre.strip()[:100],
            clavei18n=(clave_i18n or "").strip() or None,
        )
        mysql_db.add(position)
        mysql_db.commit()
        mysql_db.refresh(position)
        return position

    @staticmethod
    def update_position(
        mysql_db: Session,
        position_id: int,
        posicion_nombre: str,
        clave_i18n: Optional[str] = None,
    ) -> Optional[Posiciones]:
        position = (
            mysql_db.query(Posiciones)
            .filter(Posiciones.PosicionId == position_id)
            .first()
        )
        if not position:
            return None
        position.PosicionNombre = posicion_nombre.strip()[:100]
        position.clavei18n = (clave_i18n or "").strip() or None
        mysql_db.commit()
        mysql_db.refresh(position)
        return position

    @staticmethod
    def delete_position(mysql_db: Session, position_id: int) -> bool:
        position = (
            mysql_db.query(Posiciones)
            .filter(Posiciones.PosicionId == position_id)
            .first()
        )
        if not position:
            return False
        try:
            mysql_db.delete(position)
            mysql_db.commit()
            return True
        except IntegrityError:
            mysql_db.rollback()
            raise ValueError("POSITION_IN_USE")

    @staticmethod
    def find_linked_position_ids(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
    ) -> List[int]:
        rows = mysql_db.execute(
            select(t_tiposparteposicion.c.PosicionId).where(
                t_tiposparteposicion.c.CategoriaId == categoria_id,
                t_tiposparteposicion.c.SubCategoriaId == sub_categoria_id,
                t_tiposparteposicion.c.TipoParteId == tipo_parte_id,
            )
        ).all()
        return [int(r[0]) for r in rows]

    @staticmethod
    def link_position(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
        position_id: int,
    ) -> None:
        exists = mysql_db.execute(
            select(t_tiposparteposicion.c.PosicionId).where(
                t_tiposparteposicion.c.CategoriaId == categoria_id,
                t_tiposparteposicion.c.SubCategoriaId == sub_categoria_id,
                t_tiposparteposicion.c.TipoParteId == tipo_parte_id,
                t_tiposparteposicion.c.PosicionId == position_id,
            )
        ).first()
        if exists:
            return
        mysql_db.execute(
            insert(t_tiposparteposicion).values(
                CategoriaId=categoria_id,
                SubCategoriaId=sub_categoria_id,
                TipoParteId=tipo_parte_id,
                PosicionId=position_id,
            )
        )
        mysql_db.commit()

    @staticmethod
    def unlink_position(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
        position_id: int,
    ) -> bool:
        result = mysql_db.execute(
            delete(t_tiposparteposicion).where(
                t_tiposparteposicion.c.CategoriaId == categoria_id,
                t_tiposparteposicion.c.SubCategoriaId == sub_categoria_id,
                t_tiposparteposicion.c.TipoParteId == tipo_parte_id,
                t_tiposparteposicion.c.PosicionId == position_id,
            )
        )
        mysql_db.commit()
        return result.rowcount > 0

    @staticmethod
    def part_exists(
        mysql_db: Session,
        categoria_id: int,
        sub_categoria_id: int,
        tipo_parte_id: int,
    ) -> bool:
        return (
            mysql_db.query(Tiposparte)
            .filter(
                Tiposparte.CategoriaId == categoria_id,
                Tiposparte.SubCategoriaId == sub_categoria_id,
                Tiposparte.TipoParteId == tipo_parte_id,
            )
            .first()
            is not None
        )
