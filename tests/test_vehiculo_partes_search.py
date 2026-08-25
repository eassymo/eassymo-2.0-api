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
