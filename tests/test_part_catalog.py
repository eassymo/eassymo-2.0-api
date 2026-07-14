"""Unit tests for super-admin part catalog (synonyms, units, positions)."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.repositories.PartCatalogRepository import PartCatalogRepository
from app.services.AdminPartCatalogService import AdminPartCatalogService
from app.services.AdminWriteService import AdminWriteService
from app.services import EstandarizadorService as est_svc


def _mock_tag(**overrides):
    tag = MagicMock()
    tag.CategoriaId = overrides.get("CategoriaId", 1)
    tag.SubCategoriaId = overrides.get("SubCategoriaId", 2)
    tag.TipoParteId = overrides.get("TipoParteId", 100)
    tag.TipoParteTagId = overrides.get("TipoParteTagId", 1)
    tag.TipoParteTagDescripcion = overrides.get("TipoParteTagDescripcion", "cacahuate")
    return tag


def _mock_unit(**overrides):
    unit = MagicMock()
    unit.UnidadMedidaId = overrides.get("UnidadMedidaId", 1)
    unit.etiquetadefecto = overrides.get("etiquetadefecto", "Pieza")
    unit.clavei18n = overrides.get("clavei18n", "piece")
    return unit


def _mock_position(**overrides):
    position = MagicMock()
    position.PosicionId = overrides.get("PosicionId", 10)
    position.PosicionNombre = overrides.get("PosicionNombre", "Delantera")
    position.clavei18n = overrides.get("clavei18n", "front")
    return position


def _mock_part_type(**overrides):
    part = MagicMock()
    part.TipoParteId = overrides.get("TipoParteId", 100)
    part.TipoParteDescripcion = overrides.get("TipoParteDescripcion", "Tornillo estabilizador")
    part.CategoriaId = overrides.get("CategoriaId", 1)
    part.SubCategoriaId = overrides.get("SubCategoriaId", 2)
    return part


class TestAdminPartCatalogService:
    def test_list_part_types_paginates(self, monkeypatch):
        part = _mock_part_type()
        monkeypatch.setattr(
            PartCatalogRepository,
            "find_part_types_paginated",
            lambda db, offset, limit: ([part], 1),
        )
        result = AdminPartCatalogService.list_part_types(MagicMock(), page=1, page_size=24)
        assert result["total"] == 1
        assert result["items"][0]["tipoParteDescripcion"] == "Tornillo estabilizador"
        assert result["items"][0]["tipoParteId"] == 100
        assert result["total_pages"] == 1

    def test_list_part_tags_maps_items(self, monkeypatch):
        tag = _mock_tag()
        monkeypatch.setattr(
            PartCatalogRepository,
            "find_tags",
            lambda *args, **kwargs: [tag],
        )
        result = AdminPartCatalogService.list_part_tags(MagicMock(), 1, 2, 100)
        assert result["items"][0]["tipoParteTagDescripcion"] == "cacahuate"
        assert result["items"][0]["tipoParteTagId"] == 1

    def test_list_measurement_units_paginates(self, monkeypatch):
        unit = _mock_unit()
        monkeypatch.setattr(
            PartCatalogRepository,
            "find_units_paginated",
            lambda db, search, offset, limit: ([unit], 1),
        )
        result = AdminPartCatalogService.list_measurement_units(MagicMock(), page=1, page_size=20)
        assert result["total"] == 1
        assert result["items"][0]["etiquetaDefecto"] == "Pieza"
        assert result["total_pages"] == 1

    def test_list_part_unit_links_returns_all_and_linked(self, monkeypatch):
        unit = _mock_unit(UnidadMedidaId=3, etiquetadefecto="Par")
        monkeypatch.setattr(
            PartCatalogRepository,
            "find_all_units",
            lambda db: [unit],
        )
        monkeypatch.setattr(
            PartCatalogRepository,
            "find_linked_unit_ids",
            lambda *args, **kwargs: [3],
        )
        result = AdminPartCatalogService.list_part_unit_links(MagicMock(), 1, 2, 100)
        assert result["linkedUnitIds"] == [3]
        assert result["allUnits"][0]["unidadMedidaId"] == 3

    def test_list_part_position_links_returns_all_and_linked(self, monkeypatch):
        position = _mock_position()
        monkeypatch.setattr(
            PartCatalogRepository,
            "find_all_positions",
            lambda db: [position],
        )
        monkeypatch.setattr(
            PartCatalogRepository,
            "find_linked_position_ids",
            lambda *args, **kwargs: [10],
        )
        result = AdminPartCatalogService.list_part_position_links(MagicMock(), 1, 2, 100)
        assert result["linkedPositionIds"] == [10]
        assert result["allPositions"][0]["posicionNombre"] == "Delantera"


class TestAdminWriteServicePartCatalog:
    def test_create_part_synonym_requires_description(self):
        with pytest.raises(HTTPException) as exc:
            AdminWriteService.create_part_synonym(
                MagicMock(),
                "admin-1",
                {"categoriaId": 1, "subCategoriaId": 2, "tipoParteId": 100},
            )
        assert exc.value.status_code == 400

    def test_create_part_synonym_rejects_duplicate(self, monkeypatch):
        monkeypatch.setattr(PartCatalogRepository, "part_exists", lambda *a, **k: True)
        monkeypatch.setattr(
            PartCatalogRepository,
            "create_tag",
            lambda *a, **k: (_ for _ in ()).throw(ValueError("DUPLICATE_TAG")),
        )
        with pytest.raises(HTTPException) as exc:
            AdminWriteService.create_part_synonym(
                MagicMock(),
                "admin-1",
                {
                    "categoriaId": 1,
                    "subCategoriaId": 2,
                    "tipoParteId": 100,
                    "tipoParteTagDescripcion": "cacahuate",
                },
            )
        assert exc.value.status_code == 409

    def test_create_part_synonym_logs_audit(self, monkeypatch):
        tag = _mock_tag()
        monkeypatch.setattr(PartCatalogRepository, "part_exists", lambda *a, **k: True)
        monkeypatch.setattr(PartCatalogRepository, "create_tag", lambda *a, **k: tag)
        logged = {}
        monkeypatch.setattr(
            AdminWriteService,
            "_log_action",
            lambda admin_uid, action, entity_type, entity_id, payload=None: logged.update(
                {"action": action, "entity_type": entity_type, "entity_id": entity_id}
            ),
        )
        result = AdminWriteService.create_part_synonym(
            MagicMock(),
            "admin-1",
            {
                "categoriaId": 1,
                "subCategoriaId": 2,
                "tipoParteId": 100,
                "tipoParteTagDescripcion": "cacahuate",
            },
        )
        assert result["tipoParteTagDescripcion"] == "cacahuate"
        assert logged["action"] == "create_part_synonym"
        assert logged["entity_type"] == "part_tag"

    def test_delete_measurement_unit_in_use_raises_409(self, monkeypatch):
        monkeypatch.setattr(
            PartCatalogRepository,
            "delete_unit",
            lambda *a, **k: (_ for _ in ()).throw(ValueError("UNIT_IN_USE")),
        )
        with pytest.raises(HTTPException) as exc:
            AdminWriteService.delete_measurement_unit(MagicMock(), "admin-1", 5)
        assert exc.value.status_code == 409

    def test_link_part_unit_requires_unidad_medida_id(self):
        with pytest.raises(HTTPException) as exc:
            AdminWriteService.link_part_unit(
                MagicMock(),
                "admin-1",
                {"categoriaId": 1, "subCategoriaId": 2, "tipoParteId": 100},
            )
        assert exc.value.status_code == 400

    def test_delete_position_not_found(self, monkeypatch):
        monkeypatch.setattr(PartCatalogRepository, "delete_position", lambda *a, **k: False)
        with pytest.raises(HTTPException) as exc:
            AdminWriteService.delete_position(MagicMock(), "admin-1", 99)
        assert exc.value.status_code == 404


class TestEstandarizadorGlobalLookups:
    def test_get_all_unidades_medida(self, monkeypatch):
        unit = _mock_unit()
        monkeypatch.setattr(
            est_svc.EstandarizadorRepository,
            "find_all_unidades_medida",
            lambda db: [unit],
        )
        result = est_svc.get_all_unidades_medida(MagicMock())
        assert result["success"] is True
        assert result["lstUnidadesMedida"][0]["etiquetaDefecto"] == "Pieza"

    def test_get_all_posiciones(self, monkeypatch):
        position = _mock_position()
        monkeypatch.setattr(
            est_svc.VehiculoSensibilidadesRepository,
            "find_all_posiciones",
            lambda db: [position],
        )
        result = est_svc.get_all_posiciones(MagicMock())
        assert result["success"] is True
        assert result["lstPosiciones"][0]["posicionNombre"] == "Delantera"


class TestPartCatalogRepository:
    def test_create_tag_rejects_duplicate_description(self):
        db = MagicMock()
        existing = _mock_tag()
        db.query.return_value.filter.return_value.first.return_value = existing
        with pytest.raises(ValueError, match="DUPLICATE_TAG"):
            PartCatalogRepository.create_tag(db, 1, 2, 100, "cacahuate")

    def test_delete_unit_raises_when_in_use(self):
        db = MagicMock()
        unit = _mock_unit()
        db.query.return_value.filter.return_value.first.return_value = unit
        db.delete.side_effect = IntegrityError("stmt", {}, Exception("fk"))
        with pytest.raises(ValueError, match="UNIT_IN_USE"):
            PartCatalogRepository.delete_unit(db, 1)
        db.rollback.assert_called_once()

    def test_link_unit_is_idempotent(self):
        db = MagicMock()
        db.execute.return_value.first.return_value = (1,)
        PartCatalogRepository.link_unit(db, 1, 2, 100, 1)
        db.commit.assert_not_called()

    def test_unlink_position_returns_false_when_missing(self):
        db = MagicMock()
        result = MagicMock()
        result.rowcount = 0
        db.execute.return_value = result
        assert PartCatalogRepository.unlink_position(db, 1, 2, 100, 99) is False
