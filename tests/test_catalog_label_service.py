"""Mostrador option capture feeds the Brands / Guarantees autocomplete."""

from unittest.mock import patch

from app.services import CatalogLabelService as labels
from app.services import MostradorFolioService as svc


@patch.object(labels, "guaranteeService")
@patch.object(labels, "brandService")
def test_records_each_distinct_label_once(mock_brand, mock_guarantee):
    labels.record_option_labels(
        [
            {"brand": "FRITEC", "guarantee": "2 KM"},
            {"brand": " fritec ", "guarantee": "2  km"},
            {"brand": "Bosch", "guarantee": ""},
            {"brand": None, "guarantee": None},
        ],
        "uid-1",
    )
    assert [c.args[0].label for c in mock_brand.insert.call_args_list] == ["Bosch", "FRITEC"]
    assert [c.args[0].label for c in mock_guarantee.insert.call_args_list] == ["2 KM"]
    assert mock_brand.insert.call_args.args[0].user_uid == "uid-1"


@patch.object(labels, "guaranteeService")
@patch.object(labels, "brandService")
def test_skips_labels_already_on_saved_options(mock_brand, mock_guarantee):
    labels.record_option_labels(
        [{"brand": "FRITEC", "guarantee": "2 KM"}, {"brand": "Mann", "guarantee": "2 KM"}],
        "uid-1",
        known=[{"brand": "fritec", "guarantee": "2 km"}],
    )
    assert [c.args[0].label for c in mock_brand.insert.call_args_list] == ["Mann"]
    mock_guarantee.insert.assert_not_called()


@patch.object(labels, "guaranteeService")
@patch.object(labels, "brandService")
def test_missing_user_uses_fallback_and_errors_never_raise(mock_brand, mock_guarantee):
    labels.record_option_labels([{"brand": "Mann"}], None)
    assert mock_brand.insert.call_args.args[0].user_uid == labels.FALLBACK_USER_UID

    mock_brand.insert.side_effect = RuntimeError("mongo down")
    labels.record_option_labels([{"brand": "Mann"}], "uid-1")  # must not raise


def test_update_pieces_records_new_labels(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "shop-a",
        "creator_user": "uid-seller",
        "pieces": [{"piece_id": "p1", "name": "Aceite", "status": "pendiente", "options": []}],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(
        svc.folioRepository, "set_pieces", lambda fid, pieces, at: {**doc, "pieces": pieces}
    )
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")
    monkeypatch.setattr(svc, "sync_assigned_folio", lambda *a, **k: None)

    next_pieces = [
        {
            **doc["pieces"][0],
            "status": "cotizada",
            "options": [
                {"brand": "FRITEC", "guarantee": "2 KM", "price": 200, "ready": True},
                {"brand": "No Price", "guarantee": "x"},
                {"brand": "", "guarantee": "y", "price": 10},
            ],
        }
    ]
    with patch.object(labels, "brandService") as mock_brand, patch.object(
        labels, "guaranteeService"
    ) as mock_guarantee:
        svc.update_pieces("fid", next_pieces)

    assert [c.args[0].label for c in mock_brand.insert.call_args_list] == ["FRITEC"]
    assert [c.args[0].label for c in mock_guarantee.insert.call_args_list] == ["2 KM"]
    assert mock_brand.insert.call_args.args[0].user_uid == "uid-seller"


def test_shop_and_guest_options_record_labels_only_when_brand_and_price_are_filled(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "shop-a",
        "creator_user": "uid-seller",
        "pieces": [{"piece_id": "p1", "name": "Aceite", "status": "pendiente", "options": []}],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(
        svc.folioRepository, "set_piece_options", lambda *a, **k: {**doc}
    )
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")
    monkeypatch.setattr(svc, "sync_assigned_folio", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_append_activity_log", lambda *a, **k: None)

    option = {"brand": "FRITEC", "guarantee": "2 KM", "price": 200}
    with patch.object(labels, "brandService") as mock_brand, patch.object(
        labels, "guaranteeService"
    ) as mock_guarantee:
        svc._merge_piece_options(doc, "fid", "p1", [option], "shop-a", "Shop A")
        assert [c.args[0].label for c in mock_brand.insert.call_args_list] == ["FRITEC"]
        assert [c.args[0].label for c in mock_guarantee.insert.call_args_list] == ["2 KM"]

        # the guest form on /folio/<token>
        mock_brand.reset_mock()
        mock_guarantee.reset_mock()
        guest = {"brand": "GMC", "guarantee": "1 mes", "price": 199}
        svc._merge_piece_options(
            doc, "fid", "p1", [guest], "guest", None, captured_by_buyer=True, log_activity=False
        )
        assert [c.args[0].label for c in mock_brand.insert.call_args_list] == ["GMC"]
        assert [c.args[0].label for c in mock_guarantee.insert.call_args_list] == ["1 mes"]

        # half-typed guest options stay out
        mock_brand.reset_mock()
        mock_guarantee.reset_mock()
        svc._merge_piece_options(
            doc,
            "fid",
            "p1",
            [{"brand": "Sin Precio", "guarantee": "x"}, {"guarantee": "y", "price": 5}],
            "guest",
            None,
            captured_by_buyer=True,
            log_activity=False,
        )
        mock_brand.insert.assert_not_called()
        mock_guarantee.insert.assert_not_called()
