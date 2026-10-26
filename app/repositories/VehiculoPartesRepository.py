from typing import Callable, List, Set, Tuple, TypeVar
import logging
from sqlalchemy.exc import DBAPIError, OperationalError, PendingRollbackError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func, select, exists, text, tuple_

from models import Tiposparte, Tipospartetag, Categorias, Subcategorias

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _is_dead_mysql_session(exc: BaseException) -> bool:
    """True when the pooled connection died and the Session must be rolled back."""
    if isinstance(exc, PendingRollbackError):
        return True
    if isinstance(exc, OperationalError):
        return True
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True
    message = str(exc).lower()
    return "gone away" in message or "broken pipe" in message


def _rollback_quietly(mysql_db: Session) -> None:
    try:
        mysql_db.rollback()
    except Exception:
        logger.debug("rollback after part search failure failed", exc_info=True)


def _call_with_reconnect(mysql_db: Session, fn: Callable[[], _T]) -> _T:
    """Run fn once more after rollback when MySQL dropped the connection."""
    try:
        return fn()
    except Exception as exc:
        if not _is_dead_mysql_session(exc):
            raise
        logger.warning("MySQL connection dropped during part search (%s); retrying", exc)
        _rollback_quietly(mysql_db)
        return fn()


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
        def _read_keys() -> Set[Tuple[int, int, int]]:
            keys_desc = set(mysql_db.execute(stmt_desc, params).all())
            keys_tag = set(mysql_db.execute(stmt_tag, params).all())
            return keys_desc | keys_tag

        try:
            return _call_with_reconnect(mysql_db, _read_keys)
        except Exception as exc:
            logger.warning(
                "FULLTEXT part search unavailable (%s); using regex fallback",
                exc,
            )
            # A failed statement invalidates the transaction. Roll it back or the
            # regex fallback raises PendingRollbackError and aborts the request.
            _rollback_quietly(mysql_db)
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
        def _count() -> int:
            q = VehiculoPartesRepository._base_filter_query(mysql_db, regex)
            return q.count()

        return _call_with_reconnect(mysql_db, _count)

    @staticmethod
    def find_partes_paginated(
        mysql_db: Session,
        regex: str,
        offset: int,
        limit: int,
    ) -> List[Tiposparte]:
        def _load() -> List[Tiposparte]:
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

        return _call_with_reconnect(mysql_db, _load)
