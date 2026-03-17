from typing import List, Set, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func, select, exists, text, tuple_

from models import Tiposparte, Tipospartetag, Categorias, Subcategorias


def _escape_boolean_word(w: str) -> str:
    """Escape FULLTEXT BOOLEAN special chars so the word is safe to pass to AGAINST."""
    for c in "+-><()\"~*\\":
        if c in w:
            return '"' + w.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return w


class VehiculoPartesRepository:

    @staticmethod
    def _base_filter_query(mysql_db: Session, regex: str):
        desc_match = func.lower(Tiposparte.TipoParteDescripcion).op("REGEXP")(regex)
        tag_exists = exists(
            select(1)
            .select_from(Tipospartetag)
            .where(Tipospartetag.CategoriaId == Tiposparte.CategoriaId)
            .where(Tipospartetag.SubCategoriaId == Tiposparte.SubCategoriaId)
            .where(Tipospartetag.TipoParteId == Tiposparte.TipoParteId)
            .where(
                func.lower(Tipospartetag.TipoParteTagDescripcion).op("REGEXP")(regex)
            )
        )
        return (
            mysql_db.query(Tiposparte)
            .filter(Tiposparte.TipoParteActivo == 1)
            .filter(or_(desc_match, tag_exists))
        )

    @staticmethod
    def _part_keys_for_boolean_query(
        mysql_db: Session, boolean_query: str
    ) -> Set[Tuple[int, int, int]]:
        """Part keys (CategoriaId, SubCategoriaId, TipoParteId) matching ANY word in boolean_query (description or tag). Uses trailing * for prefix match so e.g. 'balat' matches 'balata'."""
        safe = " ".join(_escape_boolean_word(w) + "*" for w in boolean_query.split())
        if not safe.strip():
            return set()
        params = {"q": safe}
        stmt_desc = (
            select(Tiposparte.CategoriaId, Tiposparte.SubCategoriaId, Tiposparte.TipoParteId)
            .where(Tiposparte.TipoParteActivo == 1)
            .where(text("MATCH(tiposparte.TipoParteDescripcion) AGAINST (:q IN BOOLEAN MODE)"))
        )
        stmt_tag = (
            select(Tiposparte.CategoriaId, Tiposparte.SubCategoriaId, Tiposparte.TipoParteId)
            .select_from(Tipospartetag)
            .join(
                Tiposparte,
                (Tipospartetag.CategoriaId == Tiposparte.CategoriaId)
                & (Tipospartetag.SubCategoriaId == Tiposparte.SubCategoriaId)
                & (Tipospartetag.TipoParteId == Tiposparte.TipoParteId),
            )
            .where(Tiposparte.TipoParteActivo == 1)
            .where(
                text(
                    "MATCH(tipospartetag.TipoParteTagDescripcion) AGAINST (:q IN BOOLEAN MODE)"
                )
            )
        )
        try:
            keys_desc = set(mysql_db.execute(stmt_desc, params).all())
            keys_tag = set(mysql_db.execute(stmt_tag, params).all())
            return keys_desc | keys_tag
        except Exception:
            return set()

    @staticmethod
    def count_by_fulltext_variants(
        mysql_db: Session, variant_groups: List[List[str]]
    ) -> int:
        if not variant_groups:
            return 0
        keys = None
        for group in variant_groups:
            boolean_query = " ".join(group)
            group_keys = VehiculoPartesRepository._part_keys_for_boolean_query(
                mysql_db, boolean_query
            )
            if keys is None:
                keys = group_keys
            else:
                keys = keys & group_keys
            if not keys:
                return 0
        return len(keys)

    @staticmethod
    def find_partes_paginated_fulltext_variants(
        mysql_db: Session,
        variant_groups: List[List[str]],
        offset: int,
        limit: int,
    ) -> List[Tiposparte]:
        if not variant_groups:
            return []
        keys = None
        for group in variant_groups:
            boolean_query = " ".join(group)
            group_keys = VehiculoPartesRepository._part_keys_for_boolean_query(
                mysql_db, boolean_query
            )
            if keys is None:
                keys = group_keys
            else:
                keys = keys & group_keys
            if not keys:
                return []
        keys_list = list(keys)
        q = (
            mysql_db.query(Tiposparte)
            .filter(
                tuple_(
                    Tiposparte.CategoriaId,
                    Tiposparte.SubCategoriaId,
                    Tiposparte.TipoParteId,
                ).in_(keys_list)
            )
            .options(
                joinedload(Tiposparte.tipospartetag),
                joinedload(Tiposparte.subcategorias).joinedload(Subcategorias.categorias),
            )
            .order_by(Tiposparte.TipoParteDescripcion)
            .offset(offset)
            .limit(limit)
        )
        return q.all()

    @staticmethod
    def count_by_regex(mysql_db: Session, regex: str) -> int:
        q = VehiculoPartesRepository._base_filter_query(mysql_db, regex)
        return q.count()

    @staticmethod
    def find_partes_paginated(
        mysql_db: Session,
        regex: str,
        offset: int,
        limit: int,
    ) -> List[Tiposparte]:
        q = (
            VehiculoPartesRepository._base_filter_query(mysql_db, regex)
            .options(
                joinedload(Tiposparte.tipospartetag),
                joinedload(Tiposparte.subcategorias).joinedload(Subcategorias.categorias),
            )
            .order_by(Tiposparte.TipoParteDescripcion)
            .offset(offset)
            .limit(limit)
        )
        return q.all()
