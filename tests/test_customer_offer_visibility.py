"""Prices and product codes of the seller's offers: what the customer sees."""

import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import MostradorFolioService as svc
from app.services.mostrador_customer_ready import customer_view, seller_offer_count


def _folio(**extra):
    return {
        "_id": "fid",
        "status": "draft",
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Bujías",
                "options": [
                    {"brand": "NGK", "code": "BKR6E", "price": 120.0, "ready": True, "source_shop_id": "shop-a"},
                    {"brand": "Mi marca", "code": "X1", "price": 50.0, "ready": True,
                     "source_shop_id": "guest", "captured_by_buyer": True},
                ],
            }
        ],
        "customer_visible_baseline": {"pieces": [{"options": [{"brand": "NGK", "price": 120.0, "code": "BKR6E"}]}]},
        "customer_editions": [
            {"at": "t", "changes": [
                {"label": "Bujías", "detail": "Opciones: NGK $100 → NGK $120"},
                {"label": "Bujías", "detail": "Cantidad: 1 → 2"},
            ]},
        ],
        **extra,
    }


def _options(folio):
    return folio["pieces"][0]["options"]


# ---- the filter ------------------------------------------------------------


def test_defaults_show_everything_and_change_nothing():
    folio = _folio()
    assert customer_view(folio) == folio
    assert customer_view(_folio(share_prices=True, share_codes=True)) == _folio(
        share_prices=True, share_codes=True
    )


def test_prices_off_hides_only_the_price_of_the_sellers_offers():
    seller, own = _options(customer_view(_folio(share_prices=False)))
    assert seller["price"] is None and seller["price_hidden"] is True
    assert seller["code"] == "BKR6E" and "code_hidden" not in seller
    assert seller["ready"] is True  # still orderable
    assert own["price"] == 50.0 and "price_hidden" not in own  # the customer's own entry


def test_codes_off_hides_only_the_code():
    seller, own = _options(customer_view(_folio(share_codes=False)))
    assert seller["code"] is None and seller["code_hidden"] is True
    assert seller["price"] == 120.0
    assert own["code"] == "X1"


def test_each_toggle_is_independent_and_both_can_be_off():
    seller, _ = _options(customer_view(_folio(share_prices=False, share_codes=False)))
    assert seller["price"] is None and seller["code"] is None


def test_hidden_values_do_not_leak_through_the_baseline_or_edit_history():
    hidden = customer_view(_folio(share_prices=False))
    assert "customer_visible_baseline" not in hidden
    details = [c["detail"] for e in hidden["customer_editions"] for c in e["changes"]]
    assert details == ["Cantidad: 1 → 2"]
    assert "120" not in json.dumps(
        {k: v for k, v in hidden.items() if k != "pieces"}
    )


def test_visible_prices_keep_the_edit_history():
    codes_only = customer_view(_folio(share_codes=False))
    details = [c["detail"] for e in codes_only["customer_editions"] for c in e["changes"]]
    assert "Opciones: NGK $100 → NGK $120" in details
    assert "customer_visible_baseline" not in codes_only  # it quotes the hidden codes


def test_wrapped_responses_are_filtered_too():
    wrapped = customer_view({"folio": _folio(share_prices=False), "order_ids": ["o1"]})
    assert wrapped["order_ids"] == ["o1"]
    assert _options(wrapped["folio"])[0]["price"] is None
    assert customer_view({"message": "ok"}) == {"message": "ok"}


def test_seller_offer_count_ignores_the_customers_own_options():
    assert seller_offer_count(_folio()) == 1
    assert seller_offer_count({"pieces": [{"options": []}]}) == 0


# ---- every public response is filtered ------------------------------------


def test_public_get_filters_for_the_customer(monkeypatch):
    doc = _folio(share_prices=False, customer_ready=True, share_token="tok", source="counter")
    monkeypatch.setattr(svc.folioRepository, "find_by_share_token", lambda t: doc)
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda i: doc)
    monkeypatch.setattr(svc, "_ensure_mostrador_orders_materialized", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_hydrate", lambda d: {**d, "preparing": False})
    monkeypatch.setattr(svc, "sibling_draft_summaries", lambda *a, **k: [])

    customer = svc.get_by_share_token("tok", for_customer=True)
    seller = svc.get_by_share_token("tok", for_customer=False)
    assert _options(customer)[0]["price"] is None
    assert _options(seller)[0]["price"] == 120.0


def test_public_order_response_is_filtered(monkeypatch):
    from app.routers import MostradorFolioRouter as router

    doc = _folio(share_prices=False)
    monkeypatch.setattr(router.folioService, "folio_id_for_customer_change", lambda t: "fid")
    monkeypatch.setattr(router.folioService, "order_piece", lambda *a, **k: doc)

    response = router.public_order("tok", {"piece_id": "p1", "option_index": 0})
    body = json.loads(response.body)["body"]
    assert _options(body)[0]["price"] is None
    assert _options(body)[0]["price_hidden"] is True


def test_public_claim_response_is_filtered(monkeypatch):
    from app.routers import MostradorFolioRouter as router

    wrapped = {"folio": _folio(share_codes=False), "claimed": True}
    monkeypatch.setattr(router.folioService, "folio_id_for_customer_change", lambda t: "fid")
    monkeypatch.setattr(router.folioService, "claim_guest", lambda *a, **k: wrapped)

    body = json.loads(router.public_claim_guest("tok", {"guest_device_id": "d1"}).body)["body"]
    assert _options(body["folio"])[0]["code"] is None


# ---- who may change the switches, and when ---------------------------------


def _patch_update_env(monkeypatch, doc):
    saved = {}
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda i: doc)
    monkeypatch.setattr(svc.folioRepository, "edit", lambda i, data: saved.update(data) or {**doc, **data})
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")
    return saved


def test_seller_can_change_the_switches_while_nothing_is_ordered(monkeypatch):
    doc = _folio()
    saved = _patch_update_env(monkeypatch, doc)
    svc.update("fid", {"share_prices": False})
    assert saved["share_prices"] is False
    assert saved["share_codes"] is True  # untouched default


def test_switches_are_locked_in_both_directions_once_a_piece_is_ordered(monkeypatch):
    doc = _folio(share_prices=False)
    doc["pieces"][0]["order"] = {"status": "ordenada"}
    _patch_update_env(monkeypatch, doc)

    with pytest.raises(HTTPException) as turn_on:
        svc.update("fid", {"share_prices": True})
    with pytest.raises(HTTPException) as turn_off:
        svc.update("fid", {"share_codes": False})
    assert turn_on.value.status_code == turn_off.value.status_code == 409


def test_resaving_the_same_values_after_an_order_is_not_a_change(monkeypatch):
    doc = _folio(share_prices=False)
    doc["pieces"][0]["order"] = {"option_index": 0, "status": "ordenada"}
    _patch_update_env(monkeypatch, doc)
    svc.update("fid", {"share_prices": False, "share_codes": True})  # no error


def test_mark_ready_and_share_store_the_choice(monkeypatch):
    doc = _folio()
    saved = _patch_update_env(monkeypatch, doc)
    monkeypatch.setattr(svc, "get", lambda fid: {"_id": fid})
    svc.mark_customer_ready("fid", share_prices=False, share_codes=True)
    assert saved["share_prices"] is False and "share_codes" not in saved
    assert saved["customer_ready"] is True

    saved.clear()
    doc2 = _folio()
    saved2 = _patch_update_env(monkeypatch, doc2)
    monkeypatch.setattr(svc, "_resolve_client_base_url", lambda *a, **k: "https://x")
    monkeypatch.setattr(svc, "_group_name", lambda g: "Tienda")
    monkeypatch.setattr(svc, "_build_share_urls", lambda *a, **k: {})
    monkeypatch.setattr(svc, "_dispatch_notifications", lambda payload: payload)
    svc.share("fid", None, share_codes=False)
    assert saved2["share_codes"] is False and saved2["status"] == "shared"


def test_enable_for_buyer_stores_the_choice_only_on_drafts_with_offers():
    with patch("app.dependencies.group_auth.assert_group_membership"), patch(
        "app.services.MostradorFolioService.folioRepository"
    ) as repo, patch("app.services.MostradorFolioService.mark_customer_ready") as ready:
        with_offers = {**_folio(), "_id": "a", "origin_group_id": "s", "whatsapp_pending_questions": []}
        empty = {"_id": "b", "origin_group_id": "s", "status": "draft",
                 "pieces": [{"piece_id": "p", "options": []}], "whatsapp_pending_questions": []}
        repo.find_by_id.side_effect = lambda fid: {"a": with_offers, "b": empty}[fid]

        svc.enable_for_buyer(["a", "b"], False, "seller", share_prices=False, share_codes=True)

        calls = {c.args[0]: c.kwargs for c in ready.call_args_list}
        assert calls["a"] == {"share_prices": False, "share_codes": True}
        assert calls["b"] == {}
