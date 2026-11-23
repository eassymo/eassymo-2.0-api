"""Órdenes v2: deliver only in-store parts; in-person pickup respects the lock and keeps notes."""

from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.services import MostradorFolioService as svc

NOW = "2026-11-23T22:12:00Z"
OID = str(ObjectId())


def _piece(piece_id, mode, status="confirmada", order_doc_id=None, with_mode=True):
    order = {"option_index": 0, "status": status, "order_doc_id": order_doc_id}
    if with_mode:
        order["delivery_mode"] = mode
    return {"piece_id": piece_id, "name": piece_id, "options": [{"brand": "Mann", "price": 100, "ready": True}], "order": order}


def _folio(pieces, **extra):
    return {"_id": "fid", "status": "confirmed", "pieces": pieces, "customer": {"type": "guest"}, **extra}


@pytest.fixture
def repo(monkeypatch):
    """A one-folio repository: find_by_id returns it, edit records what was saved."""
    state = SimpleNamespace(doc=None, saved=None)

    def edit(folio_id, patch):
        state.saved = {**state.doc, **patch}
        return state.saved

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: state.doc)
    monkeypatch.setattr(svc.folioRepository, "edit", edit)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    monkeypatch.setattr(svc, "confirm", lambda *a, **k: None)
    return state


@pytest.fixture
def folio4(repo):
    repo.doc = _folio([_piece("t", "tienda"), _piece("pk", "pickup"), _piece("dom", "domicilio"), _piece("legacy", None, with_mode=False)])
    return repo


@pytest.fixture
def folio_pickup_only(repo):
    repo.doc = _folio([_piece("pk", "pickup"), _piece("dom", "domicilio")])
    return repo


def test_deliver_marks_only_store_and_legacy_parts(folio4):
    res = svc.complete_in_person_delivery("fid")
    modes = {p["piece_id"]: p["order"]["status"] for p in folio4.saved["pieces"]}
    assert modes == {"t": "entregada", "legacy": "entregada", "pk": "confirmada", "dom": "confirmada"}
    assert res["delivered_count"] == 2
    assert folio4.saved["pieces"][0]["order"]["delivered_at"] == NOW
    assert "delivered_at" not in folio4.saved["pieces"][1]["order"]


def test_deliver_with_no_store_parts_is_400(folio_pickup_only):
    with pytest.raises(HTTPException) as e:
        svc.complete_in_person_delivery("fid")
    assert e.value.status_code == 400 and e.value.detail == "No in-store pieces to deliver"
    assert folio_pickup_only.saved is None


def test_deliver_skips_parts_already_delivered(repo):
    repo.doc = _folio([_piece("t", "tienda", status="entregada"), _piece("t2", "tienda")])
    res = svc.complete_in_person_delivery("fid")
    assert res["delivered_count"] == 1


@pytest.fixture
def order_env(monkeypatch, repo):
    """An in-person order whose folio piece points at it."""
    state = SimpleNamespace(order_saved=None, folio_saved=None, repo=repo)
    order_doc = {"_id": ObjectId(OID), "mostrador_folio_id": "fid", "status": "x"}

    class FakeOrder:
        def __init__(self, **kw):
            self.data = dict(kw)

        def change_status(self, name):
            self.data["status"] = name

        def toJson(self):
            return dict(self.data)

    def order_edit(oid, data):
        state.order_saved = data
        return {**data, "_id": oid}

    import app.repositories as repositories
    import app.schemas.Order as order_schema

    monkeypatch.setattr(repositories.OrderRepository, "find_one", lambda q: order_doc)
    monkeypatch.setattr(repositories.OrderRepository, "edit", order_edit)
    monkeypatch.setattr(order_schema, "Order", FakeOrder)
    state.new_folio = lambda **extra: setattr(repo, "doc", _folio([_piece("pk", "pickup", order_doc_id=OID)], **extra))
    return state


@pytest.fixture
def order_on_open_folio(order_env):
    order_env.new_folio()
    order_env.__dict__["folio_saved"] = None
    return order_env


@pytest.fixture
def order_on_assigned_folio(order_env):
    order_env.new_folio(part_request_ids=["pr1"])
    return order_env


def test_pickup_refused_when_folio_assigned(order_on_assigned_folio):
    with pytest.raises(HTTPException) as e:
        svc.confirm_pickup(OID, "https://s/f.png", "Ana")
    assert e.value.status_code == 403
    assert order_on_assigned_folio.order_saved is None


def test_pickup_stores_notes_and_delivered_at(order_on_open_folio):
    svc.confirm_pickup(OID, "https://s/f.png", "Ana", ["https://s/1.jpg"], notes="Con factura")
    env = order_on_open_folio
    assert env.order_saved["delivery_notes_seller"] == "Con factura"
    assert env.order_saved["delivery_pictures_seller"] == ["https://s/1.jpg"]
    piece = env.repo.saved["pieces"][0]["order"]
    assert piece["status"] == "entregada" and piece["delivered_at"] == NOW


def test_pickup_without_notes_keeps_existing_ones(order_on_open_folio):
    svc.confirm_pickup(OID, "https://s/f.png", "Ana")
    assert "delivery_notes_seller" not in order_on_open_folio.order_saved or order_on_open_folio.order_saved["delivery_notes_seller"] is None


def test_router_forwards_pickup_notes(monkeypatch):
    from app.routers import MostradorFolioRouter as router

    seen = {}
    monkeypatch.setattr(router.folioService, "confirm_pickup", lambda *a, **k: seen.update(k) or {})
    router.confirm_pickup(
        OID,
        {"delivery_customer_signature_url": "s", "delivery_received_by_name": "Ana", "delivery_pictures_seller": ["p"], "delivery_notes_seller": "Con factura"},
    )
    assert seen["notes"] == "Con factura"


def test_pickup_twice_is_400_and_keeps_the_first_evidence(order_env):
    order_env.new_folio()
    order_env.repo.doc["pieces"][0]["order"]["status"] = "entregada"
    with pytest.raises(HTTPException) as e:
        svc.confirm_pickup(OID, "https://s/f2.png", "Otra persona")
    assert e.value.status_code == 400 and e.value.detail == "Order already delivered"
    assert order_env.order_saved is None


def test_buyer_marked_parts_are_not_delivered_by_the_seller(repo):
    bought = _piece("bought", "tienda")
    bought["options"][0]["captured_by_buyer"] = True
    repo.doc = _folio([bought, _piece("t", "tienda")])
    res = svc.complete_in_person_delivery("fid")
    statuses = {p["piece_id"]: p["order"]["status"] for p in repo.saved["pieces"]}
    assert statuses == {"bought": "confirmada", "t": "entregada"}
    assert res["delivered_count"] == 1


def test_only_buyer_marked_parts_left_is_400(repo):
    bought = _piece("bought", "tienda")
    bought["options"][0]["captured_by_buyer"] = True
    repo.doc = _folio([bought])
    with pytest.raises(HTTPException) as e:
        svc.complete_in_person_delivery("fid")
    assert e.value.detail == "No in-store pieces to deliver"
