"""pickup_at on a piece's embedded order."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.services import MostradorFolioService as svc

UTC = ZoneInfo("UTC")


@pytest.fixture
def saved(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "shop-a",
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Filtro",
                "status": "cotizada",
                "options": [{"brand": "Mann", "code": "1", "price": 50, "ready": True}],
            }
        ],
    }
    out = {}

    def fake_set_piece_order(fid, piece_id, order, updated_at):
        out.update(order)
        return {**doc, "pieces": [{**doc["pieces"][0], "order": order}]}

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc.folioRepository, "set_piece_order", fake_set_piece_order)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: datetime(2026, 11, 23, tzinfo=UTC))
    monkeypatch.setattr(svc, "sync_assigned_folio", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_ensure_mostrador_orders_materialized", lambda *a, **k: None)
    return out


def test_pickup_time_stored_for_pickup(saved):
    svc.order_piece("fid", "p1", 0, "pickup", pickup_at="2026-11-23T17:00:00-06:00")
    assert saved["pickup_at"] == datetime(2026, 11, 23, 23, 0, tzinfo=UTC)


def test_pickup_time_ignored_for_tienda(saved):
    svc.order_piece("fid", "p1", 0, "tienda", pickup_at="2026-11-23T17:00:00-06:00")
    assert saved["pickup_at"] is None


def test_pickup_time_optional(saved):
    svc.order_piece("fid", "p1", 0, "pickup")
    assert saved["pickup_at"] is None


def test_pickup_time_invalid(saved):
    with pytest.raises(HTTPException) as exc:
        svc.order_piece("fid", "p1", 0, "pickup", pickup_at="mañana")
    assert exc.value.status_code == 400
    assert exc.value.detail == "pickup_at must be ISO 8601"


def test_pickup_time_accepts_z_suffix(saved):
    svc.order_piece("fid", "p1", 0, "pickup", pickup_at="2026-11-23T23:00:00Z")
    assert saved["pickup_at"] == datetime(2026, 11, 23, 23, 0, tzinfo=UTC)


@pytest.mark.parametrize("value", ["2026-11-23T17:00:00", "2026-11-25"])
def test_pickup_time_without_offset_is_rejected(saved, value):
    with pytest.raises(HTTPException) as exc:
        svc.order_piece("fid", "p1", 0, "pickup", pickup_at=value)
    assert exc.value.status_code == 400
    assert exc.value.detail == "pickup_at must be ISO 8601"


def test_router_forwards_pickup_at(monkeypatch):
    from app.routers import MostradorFolioRouter as router

    seen = {}
    monkeypatch.setattr(router.folioService, "order_piece", lambda *a, **k: seen.update(k) or {})
    router.order_piece("fid", {"piece_id": "p1", "option_index": 0, "delivery_mode": "pickup", "pickup_at": "2026-11-23T23:00:00Z"})
    assert seen["pickup_at"] == "2026-11-23T23:00:00Z"
