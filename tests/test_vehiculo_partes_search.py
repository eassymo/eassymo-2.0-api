from unittest.mock import MagicMock

from app.schemas.VehiculoPartesSearch import SearchPartesPaginatorRequest
from app.services import VehiculoPartesService as svc


def _part(description: str):
    part = MagicMock()
    part.TipoParteId = 56328
    part.TipoParteDescripcion = description
    part.TipoParteSensibleMotor = False
    part.TipoParteSensiblePosicion = False
    part.TipoParteSensibleRin = False
    part.TipoSensibleAnillosMotor = False
    part.CategoriaId = 3
    part.SubCategoriaId = 138
    part.tipospartetag = []
    part.subcategorias.SubCategoriaId = 138
    part.subcategorias.SubCategoriaDescripcion = "Pastillas"
    part.subcategorias.categorias.CategoriaId = 3
    part.subcategorias.categorias.CategoriaDescripcion = "Frenos"
    return part


def test_search_partes_falls_back_to_regex_when_fulltext_is_empty(monkeypatch):
    monkeypatch.setattr(
        svc.VehiculoPartesRepository,
        "count_by_fulltext_variants",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        svc.VehiculoPartesRepository,
        "find_partes_paginated_fulltext_variants",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        svc.VehiculoPartesRepository,
        "count_by_regex",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        svc.VehiculoPartesRepository,
        "find_partes_paginated",
        lambda *args, **kwargs: [_part("Balatas")],
    )

    payload = SearchPartesPaginatorRequest(
        historicoBusqueda={"criterio": "bala"},
        page=0,
        itemsPerPage=20,
    )
    result = svc.search_partes_paginator(MagicMock(), payload)

    descriptions = [
        item["tipoParteDescripcion"]
        for item in result["historicoBusqueda"]["details"][0]["partes"]
    ]
    assert result["count"] == 1
    assert "Balatas" in descriptions


def test_fulltext_retries_after_mysql_gone_away():
    from sqlalchemy.exc import OperationalError

    from app.repositories.VehiculoPartesRepository import VehiculoPartesRepository

    session = MagicMock()
    boom = OperationalError(
        "SELECT",
        {},
        Exception("MySQL server has gone away (BrokenPipeError(32, 'Broken pipe'))"),
    )
    ok = MagicMock()
    ok.all.return_value = [(7, 182, 13664)]
    session.execute.side_effect = [boom, ok, ok]

    keys = VehiculoPartesRepository._part_keys_for_boolean_query(session, "sensor")

    session.rollback.assert_called()
    assert (7, 182, 13664) in keys
    assert session.execute.call_count == 3


def test_fulltext_failure_rolls_back_before_regex_fallback():
    from app.repositories.VehiculoPartesRepository import VehiculoPartesRepository

    session = MagicMock()
    session.execute.side_effect = Exception("Can't find FULLTEXT index")

    keys = VehiculoPartesRepository._part_keys_for_boolean_query(session, "sensor")

    assert keys == set()
    session.rollback.assert_called_once()
    assert session.execute.call_count == 1


def test_regex_count_retries_after_pending_rollback():
    from sqlalchemy.exc import PendingRollbackError

    from app.repositories.VehiculoPartesRepository import VehiculoPartesRepository

    session = MagicMock()
    query = MagicMock()
    query.count.side_effect = [
        PendingRollbackError(
            "Can't reconnect until invalid transaction is rolled back"
        ),
        2,
    ]
    original = VehiculoPartesRepository._base_filter_query
    VehiculoPartesRepository._base_filter_query = staticmethod(
        lambda *_args, **_kwargs: query
    )
    try:
        total = VehiculoPartesRepository.count_by_regex(session, "sensor")
    finally:
        VehiculoPartesRepository._base_filter_query = original

    assert total == 2
    session.rollback.assert_called_once()
