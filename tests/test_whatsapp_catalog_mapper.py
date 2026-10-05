from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.repositories.WhatsappIntakeSessionRepository import (
    STATUS_COLLECTING,
    append_message,
    bump_generation,
    open_session,
)
from app.schemas.WhatsappExtraction import ExtractionLine, ExtractionVehicle, WhatsappExtractionProposal, ExtractionIntent, ExtractionUncertainty
from app.services.WhatsappCatalogMapper import (
    WhatsappCatalogMapper,
    strip_position_tokens,
    _pick_catalog_match,
    _score_catalog_item,
    vehicle_search_terms,
    year_from_bodies,
)


def test_score_catalog_item_prefers_exact_match():
    assert _score_catalog_item("balata", "Balatas") >= 80
    assert _score_catalog_item("balata", "Ajustadores De Balata") < 55


def test_strip_position_tokens_removes_delantera():
    assert strip_position_tokens("balatas delanteras", "delantera") == "balatas"


@patch("app.services.WhatsappCatalogMapper.search_partes_paginator")
def test_pick_catalog_match_returns_balatas_for_balata(mock_search):
    mock_search.return_value = {
        "historicoBusqueda": {
            "details": [
                {
                    "partes": [
                        {
                            "tipoParteId": 10,
                            "tipoParteDescripcion": "Balatas",
                            "categoriaId": 1,
                            "subCategoriaId": 2,
                            "tipoParteSensiblePosicion": True,
                        },
                        {
                            "tipoParteId": 11,
                            "tipoParteDescripcion": "Ajustadores De Balata",
                            "categoriaId": 1,
                            "subCategoriaId": 2,
                            "tipoParteSensiblePosicion": False,
                        },
                    ]
                }
            ]
        }
    }
    match = _pick_catalog_match(MagicMock(), "balata")
    assert match is not None
    assert match["tipoParteDescripcion"] == "Balatas"


@patch("app.services.WhatsappCatalogMapper.search_partes_paginator")
def test_pick_catalog_match_stays_unmatched_when_ambiguous(mock_search):
    mock_search.return_value = {
        "historicoBusqueda": {
            "details": [
                {
                    "partes": [
                        {
                            "tipoParteId": 10,
                            "tipoParteDescripcion": "Filtro de aceite",
                            "categoriaId": 1,
                            "subCategoriaId": 2,
                        },
                        {
                            "tipoParteId": 11,
                            "tipoParteDescripcion": "Filtro de aire",
                            "categoriaId": 1,
                            "subCategoriaId": 2,
                        },
                    ]
                }
            ]
        }
    }
    assert _pick_catalog_match(MagicMock(), "filtro") is None


@patch("app.services.WhatsappCatalogMapper.get_unidades_medida_by_parte")
@patch("app.services.WhatsappCatalogMapper.VehiculoSensibilidadesRepository.find_posiciones_by_tipo_parte")
@patch("app.services.WhatsappCatalogMapper._pick_catalog_match")
def test_map_line_maps_balatas_delantera(mock_pick, mock_posiciones, mock_units):
    mock_pick.return_value = {
        "tipoParteId": 10,
        "tipoParteDescripcion": "Balatas",
        "categoriaId": 1,
        "subCategoriaId": 2,
        "tipoParteSensiblePosicion": True,
    }
    pos = MagicMock()
    pos.PosicionNombre = "Delantera"
    mock_posiciones.return_value = [pos]
    mock_units.return_value = {
        "lstUnidadesMedida": [{"etiquetaDefecto": "Pieza"}],
    }

    mapped = WhatsappCatalogMapper().map_line(
        MagicMock(),
        ExtractionLine(
            local_id="l1",
            part_name="balatas",
            quantity=1,
            unit="pieza",
            position="delantera",
        ),
    )

    assert mapped.tipo_parte_id == "10"
    assert mapped.name == "Balatas"
    assert mapped.position == "Delantera"
    assert mapped.position_suggested is True
    assert mapped.catalog_matched is True


@patch("app.config.database.db")
def test_append_message_sets_flush_at_once(mock_db):
    col = MagicMock()
    mock_db.__getitem__.return_value = col
    now = datetime.now(timezone.utc)
    first = {
        "from_number": "+521",
        "status": STATUS_COLLECTING,
        "messages": [{"body": "first"}],
        "generation": 1,
        "flush_at": now + timedelta(seconds=8),
    }
    col.find_one_and_update.return_value = first

    first_session, auto_flush, schedule = append_message(
        "+521",
        {"body": "first"},
        quiet_seconds=8,
    )
    assert schedule is True
    assert first_session["flush_at"] is not None

    second = {
        **first,
        "messages": [{"body": "first"}, {"body": "second"}],
    }
    col.find_one_and_update.return_value = second

    second_session, _, schedule_again = append_message(
        "+521",
        {"body": "second"},
        quiet_seconds=8,
    )
    assert schedule_again is False
    assert second_session["flush_at"] == first_session["flush_at"]
    assert auto_flush is False


@patch("app.config.database.db")
def test_bump_generation_increments_for_listo(mock_db):
    col = MagicMock()
    mock_db.__getitem__.return_value = col
    session = {
        "from_number": "+521",
        "status": STATUS_COLLECTING,
        "generation": 1,
    }
    bumped = {**session, "generation": 2}
    col.find_one.side_effect = [session, bumped]

    result = bump_generation("+521")
    assert result["generation"] == 2


def test_vehicle_search_terms_keeps_koleos_from_burst():
    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        vehicle=ExtractionVehicle(year="2020"),
        lines=[
            ExtractionLine(local_id="a", part_name="sensor de detonación", quantity=1),
            ExtractionLine(
                local_id="b",
                part_name="balatas",
                quantity=1,
                position="delantera",
                raw="Y también unas balatas delanteras",
            ),
        ],
    )
    terms = vehicle_search_terms(
        proposal,
        [
            "Te encargo pa una koleos",
            "2020",
            "Un sensor de detonación porfa",
            "Y también unas balatas delanteras",
        ],
    )
    assert "koleos" in [term.lower() for term in terms]


def test_year_from_bodies_uses_standalone_year_bubble():
    assert (
        year_from_bodies(
            [
                "Te encargo pa una koleos",
                "2020",
                "Un sensor de detonación porfa",
                "Y también unas balatas delanteras",
            ]
        )
        == "2020"
    )


def test_year_from_bodies_ignores_implausible_and_conflicting_years():
    assert year_from_bodies(["filtro", "99"]) is None
    assert year_from_bodies(["2015", "2020"]) is None


def test_year_from_bodies_uses_single_mentioned_year():
    assert year_from_bodies(["Jetta 2015, filtro de aire"]) == "2015"


@patch("app.services.WhatsappCatalogMapper.AcesVehiclesService.find_aces_vehicles")
def test_map_vehicle_fills_year_glm_dropped_from_standalone_bubble(mock_find):
    hit = MagicMock()
    hit.VehiculoFabricante = "Renault"
    hit.VehiculoModelo = "Koleos"
    mock_find.return_value = [hit]

    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        vehicle=ExtractionVehicle(make=None, model=None, year=None),
        lines=[ExtractionLine(local_id="a", part_name="sensor de detonación", quantity=1)],
    )
    mapped = WhatsappCatalogMapper().map_vehicle(
        MagicMock(),
        proposal,
        [
            "Te encargo pa una koleos",
            "2020",
            "Un sensor de detonación porfa",
            "Y también unas balatas delanteras",
        ],
    )
    assert mapped is not None
    assert mapped.year == "2020"
    assert mapped.make == "Renault"
    assert mapped.model == "Koleos"
    assert mock_find.call_args.args[2] == "2020"


@patch("app.services.WhatsappCatalogMapper.AcesVehiclesService.find_aces_vehicles")
def test_map_vehicle_resolves_koleos_2020(mock_find):
    hit = MagicMock()
    hit.VehiculoFabricante = "Renault"
    hit.VehiculoModelo = "Koleos"
    mock_find.return_value = [hit]

    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        vehicle=ExtractionVehicle(year="2020"),
        uncertainties=[
            ExtractionUncertainty(
                path="vehicle.make",
                reason="No se menciona la marca",
            )
        ],
        lines=[ExtractionLine(local_id="a", part_name="sensor de detonación", quantity=1)],
    )
    mapped = WhatsappCatalogMapper().map_vehicle(
        MagicMock(),
        proposal,
        ["Te encargo pa una koleos", "2020"],
    )
    assert mapped is not None
    assert mapped.make == "Renault"
    assert mapped.model == "Koleos"
    assert mapped.year == "2020"
    mock_find.assert_called()
    assert mock_find.call_args.args[1].lower() == "koleos"
    assert mock_find.call_args.args[2] == "2020"


@patch("app.services.WhatsappCatalogMapper.AcesVehiclesService.find_aces_vehicles")
def test_map_vehicle_skips_ambiguous_hits(mock_find):
    first = MagicMock(VehiculoFabricante="Renault", VehiculoModelo="Koleos")
    second = MagicMock(VehiculoFabricante="Nissan", VehiculoModelo="Koleos")
    mock_find.return_value = [first, second]
    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        vehicle=ExtractionVehicle(year="2020"),
    )
    mapped = WhatsappCatalogMapper().map_vehicle(MagicMock(), proposal, ["koleos"])
    assert mapped is not None
    assert mapped.make is None
    assert mapped.model is None
