"""Unit tests for mostrador multi-shop scoping and invite helpers."""

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock, patch

from app.services import MostradorFolioService as svc


def test_scope_options_for_shop_filters_other_bids():
    doc = {
        "pieces": [
            {
                "piece_id": "p1",
                "options": [
                    {"brand": "A", "source_shop_id": "shop-a"},
                    {"brand": "B", "source_shop_id": "shop-b"},
                ],
            }
        ]
    }
    scoped = svc._scope_options_for_shop(doc, "shop-a")
    assert len(scoped["pieces"][0]["options"]) == 1
    assert scoped["pieces"][0]["options"][0]["brand"] == "A"


def test_get_tube_applies_option_scoping(monkeypatch):
    doc = {
        "_id": "fid",
        "participant_shops": [
            {"tube_token": "tube-1", "name": "Refaccionaria Norte", "eassymo": False},
            {"tube_token": "tube-2", "name": "Otra tienda", "eassymo": False},
        ],
        "pieces": [
            {
                "piece_id": "p1",
                "options": [
                    {"brand": "Mine", "source_shop_id": "tube-1"},
                    {"brand": "Other", "source_shop_id": "tube-2"},
                ],
            }
        ],
        "visibility": {"tube-1": ["p1"]},
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_tube_token", lambda token: doc)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)

    result = svc.get_tube("tube-1")
    assert len(result["pieces"][0]["options"]) == 1
    assert result["pieces"][0]["options"][0]["brand"] == "Mine"
    assert result["tube_shop"]["name"] == "Refaccionaria Norte"
    assert len(result["participant_shops"]) == 1
    assert result["participant_shops"][0]["tube_token"] == "tube-1"


def test_get_for_group_rejects_non_participant(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "participant_shops": [],
        "pieces": [],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)

    with pytest.raises(HTTPException) as exc:
        svc.get_for_group("fid", "other-group")
    assert exc.value.status_code == 403


def test_get_for_group_scopes_invited_participant(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "participant_shops": [{"group_id": "g-invited", "eassymo": True, "name": "Refa"}],
        "visibility": {"g-invited": ["p1"]},
        "pieces": [
            {
                "piece_id": "p1",
                "options": [
                    {"brand": "Mine", "source_shop_id": "g-invited"},
                    {"brand": "Other", "source_shop_id": "origin-1"},
                ],
            },
            {"piece_id": "p2", "options": []},
        ],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)

    result = svc.get_for_group("fid", "g-invited")
    assert len(result["pieces"]) == 1
    assert result["pieces"][0]["piece_id"] == "p1"
    assert len(result["pieces"][0]["options"]) == 1
    assert result["pieces"][0]["options"][0]["brand"] == "Mine"


def test_get_for_group_scopes_origin_seller_options(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "participant_shops": [],
        "pieces": [
            {
                "piece_id": "p1",
                "options": [
                    {"brand": "Mine", "source_shop_id": "origin-1"},
                    {"brand": "Competitor", "source_shop_id": "other-shop"},
                ],
            },
            {"piece_id": "p2", "options": []},
        ],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)

    result = svc.get_for_group("fid", "origin-1")
    assert len(result["pieces"]) == 2
    assert len(result["pieces"][0]["options"]) == 1
    assert result["pieces"][0]["options"][0]["brand"] == "Mine"


def test_merge_part_request_offers_into_folio_adds_seller_offers(monkeypatch):
    doc = {
        "_id": "folio-1",
        "origin_group_id": "origin-1",
        "customer": {"group_id": "buyer-1", "user_uid": "buyer-uid"},
        "pieces": [
            {
                "piece_id": "p1",
                "status": "cotizada",
                "options": [
                    {
                        "brand": "HSBS",
                        "code": "66",
                        "price": 299,
                        "ready": True,
                        "source_shop_id": "origin-1",
                    },
                ],
            },
        ],
    }

    monkeypatch.setattr(
        "app.repositories.PartRequestRepository.find",
        lambda filters, projection: [
            {
                "_id": "pr-1",
                "mostrador_piece_id": "p1",
                "mostrador_folio_id": "folio-1",
                "isActive": True,
            }
        ],
    )
    monkeypatch.setattr(
        "app.repositories.OfferRepository.find",
        lambda filters, projection: [
            {
                "brand": "Bosch",
                "code": "99",
                "price": 450,
                "guarantee": "12 meses",
                "group_id": "origin-1",
                "group_info": {"name": "Origin Shop"},
                "status": "Created",
            }
        ],
    )

    result = svc._merge_part_request_offers_into_folio(doc, "origin-1")
    brands = [opt["brand"] for opt in result["pieces"][0]["options"]]
    assert brands == ["HSBS", "Bosch"]


def test_get_for_group_merges_part_request_offers_for_assigned_folio(monkeypatch):
    doc = {
        "_id": "folio-1",
        "origin_group_id": "origin-1",
        "customer": {"group_id": "buyer-1", "user_uid": "buyer-uid"},
        "participant_shops": [],
        "pieces": [
            {
                "piece_id": "p1",
                "status": "cotizada",
                "options": [
                    {
                        "brand": "HSBS",
                        "code": "66",
                        "price": 299,
                        "ready": True,
                        "source_shop_id": "origin-1",
                    },
                ],
            },
        ],
    }

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(
        svc,
        "_merge_part_request_offers_into_folio",
        lambda folio_doc, shop_group_id: {
            **folio_doc,
            "pieces": [
                {
                    **folio_doc["pieces"][0],
                    "options": [
                        *folio_doc["pieces"][0]["options"],
                        {
                            "brand": "Bosch",
                            "code": "99",
                            "price": 450,
                            "ready": True,
                            "source_shop_id": "origin-1",
                        },
                    ],
                }
            ],
        },
    )

    result = svc.get_for_group("folio-1", "origin-1")
    brands = [opt["brand"] for opt in result["pieces"][0]["options"]]
    assert brands == ["HSBS", "Bosch"]


def test_confirm_guest_option_tags_shop(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "participant_shops": [],
        "pieces": [
            {
                "piece_id": "p1",
                "status": "cotizando",
                "options": [
                    {
                        "brand": "Monroe",
                        "captured_by_buyer": True,
                        "source_confirmation": "not_confirmed_by_shop",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_group_name", lambda gid: "Origin Shop")
    monkeypatch.setattr(
        svc.folioRepository,
        "set_piece_options",
        lambda fid, piece_id, options, status, ts: (
            doc["pieces"][0].update({"options": options, "status": status}) or doc
        ),
    )
    monkeypatch.setattr(svc, "sync_assigned_folio", lambda fid: None)
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)

    result = svc.confirm_guest_option("fid", "p1", 0, "origin-1")
    opt = result["pieces"][0]["options"][0]
    assert opt["source_confirmation"] == "confirmed"
    assert opt["captured_by_buyer"] is False
    assert opt["source_shop_id"] == "origin-1"


def test_invite_shop_eassymo_returns_notification(monkeypatch):
    doc = {"_id": "fid", "customer": {"name": "Cliente"}, "pieces": []}
    updated = {
        **doc,
        "participant_shops": [{"group_id": "g2", "eassymo": True}],
        "visibility": {},
    }

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc.folioRepository, "push_participant_shop", lambda *a, **k: updated)
    monkeypatch.setattr(svc.folioRepository, "edit", lambda fid, data: updated)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")

    mock_group = MagicMock()
    mock_group.find_by_id.return_value = {"owner": "uid-1", "name": "Refa"}
    monkeypatch.setitem(
        __import__("sys").modules,
        "app.repositories.GroupRepository",
        mock_group,
    )

    with patch("app.repositories.GroupRepository") as grp_repo:
        grp_repo.find_by_id.return_value = {"owner": "uid-1", "name": "Refa"}
        with patch("app.factories.NotificationsCreator") as notif_creator:
            mock_notif = MagicMock()
            mock_notif.model_dump.return_value = {
                "type": "MOSTRADOR_SHOP_INVITED",
                "message": "invited",
                "owner": "uid-1",
                "ownerGroup": "g2",
            }
            notif_creator.create_mostrador_shop_invited_notification.return_value = mock_notif

            result = svc.invite_shop(
                "fid",
                group_id="g2",
                name="Refa",
                eassymo=True,
                visible_piece_ids=["p1"],
            )

    assert result.get("notification") is not None
    assert result["notification"]["type"] == "MOSTRADOR_SHOP_INVITED"


def test_submit_group_options_allows_origin(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "participant_shops": [],
        "pieces": [{"piece_id": "p1", "status": "pendiente", "options": []}],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_group_name", lambda gid: "Origin Shop")
    monkeypatch.setattr(
        svc,
        "_merge_piece_options",
        lambda doc, folio_id, piece_id, options, **kwargs: {
            **doc,
            "pieces": [{"piece_id": "p1", "options": options}],
        },
    )

    result = svc.submit_group_options("fid", "p1", [{"brand": "Bosch"}], "origin-1")
    assert result["pieces"][0]["options"][0]["brand"] == "Bosch"


def test_add_piece_by_shop_appends_visibility_for_participant(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "participant_shops": [{"group_id": "g2", "eassymo": True, "name": "Refa"}],
        "visibility": {"g2": ["p1"]},
        "pieces": [{"piece_id": "p1", "options": []}],
    }
    edited = {}

    def fake_set_pieces(fid, pieces, ts):
        doc["pieces"] = pieces

    def fake_edit(fid, data):
        edited.update(data)
        doc.update(data)

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc.folioRepository, "set_pieces", fake_set_pieces)
    monkeypatch.setattr(svc.folioRepository, "edit", fake_edit)
    monkeypatch.setattr(svc, "_group_name", lambda gid: "Refa")
    monkeypatch.setattr(svc, "sync_assigned_folio", lambda fid: None)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)

    result = svc.add_piece_by_shop("fid", "g2", {"name": "Balata"})
    new_id = result["pieces"][0]["piece_id"]
    assert result["pieces"][0]["name"] == "Balata"
    assert result["pieces"][0]["added_by_shop_id"] == "g2"
    assert new_id in edited["visibility"]["g2"]


def test_invite_shop_captured_by_buyer_persists_flag(monkeypatch):
    doc = {"_id": "fid", "customer": {"name": "Cliente"}, "pieces": []}
    captured_shop = {}

    def fake_push(fid, shop, visible_piece_ids, ts):
        nonlocal captured_shop
        captured_shop = shop
        return {**doc, "participant_shops": [shop], "visibility": {}}

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc.folioRepository, "push_participant_shop", fake_push)
    monkeypatch.setattr(svc.folioRepository, "edit", lambda fid, data: {**doc, **data})
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")
    monkeypatch.setattr(svc, "_build_share_urls", lambda *a, **k: {"share_path": "/pos/tube/x"})

    svc.invite_shop(
        "fid",
        group_id=None,
        name="Refaccionaria del Centro",
        eassymo=False,
        visible_piece_ids=["p1"],
        captured_by_buyer=True,
    )

    assert captured_shop["captured_by_buyer"] is True
    assert captured_shop["name"] == "Refaccionaria del Centro"
    assert captured_shop["tube_token"]


def test_submit_guest_piece_options_with_shop_id(monkeypatch):
    doc = {
        "_id": "fid",
        "pieces": [{"piece_id": "p1", "status": "pendiente", "options": []}],
    }
    merged_kwargs = {}

    def fake_merge(*args, **kwargs):
        merged_kwargs.update(kwargs)
        options = args[3] if len(args) > 3 else []
        return {**doc, "pieces": [{"piece_id": "p1", "options": options}]}

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_merge_piece_options", fake_merge)

    result = svc.submit_guest_piece_options(
        "fid",
        "p1",
        [{"brand": "Monroe", "price": 450}],
        shop_id="tube-abc",
        shop_name="Refaccionaria del Centro",
    )

    assert merged_kwargs["shop_id"] == "tube-abc"
    assert merged_kwargs["shop_name"] == "Refaccionaria del Centro"
    assert merged_kwargs["captured_by_buyer"] is True
    assert result["pieces"][0]["options"][0]["brand"] == "Monroe"


def test_order_piece_skips_materialization_for_buyer_capture(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "pieces": [
            {
                "piece_id": "p1",
                "status": "cotizada",
                "options": [
                    {
                        "brand": "Monroe",
                        "price": 450,
                        "captured_by_buyer": True,
                        "source_shop_id": "tube-abc",
                    }
                ],
            }
        ],
    }
    materialized = {"called": False}

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_require_seller_folio_editable", lambda d: None)
    monkeypatch.setattr(svc.folioRepository, "set_piece_order", lambda *a, **k: doc)
    monkeypatch.setattr(svc, "sync_assigned_folio", lambda fid: None)
    monkeypatch.setattr(
        svc,
        "_ensure_mostrador_orders_materialized",
        lambda fid: materialized.update({"called": True}),
    )
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)

    svc.order_piece("fid", "p1", 0)

    assert materialized["called"] is False


def test_get_redirect_info_returns_minimal_fields(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "share_token": "token-abc",
        "status": "draft",
        "folio_code": "ABC123",
        "pieces": [{"piece_id": "p1", "name": "secret"}],
        "customer": {"name": "Cliente"},
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)

    result = svc.get_redirect_info("fid")

    assert result == {
        "origin_group_id": "origin-1",
        "share_token": "token-abc",
        "status": "draft",
        "folio_code": "ABC123",
    }
    assert "pieces" not in result
    assert "customer" not in result


def test_get_redirect_info_backfills_missing_share_token(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "share_token": None,
        "status": "draft",
        "folio_code": "ABC123",
    }
    edited = {}

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(
        svc.folioRepository,
        "edit",
        lambda fid, data: edited.update(data) or {**doc, **data},
    )
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")

    result = svc.get_redirect_info("fid")

    assert result["share_token"]
    assert edited["share_token"] == result["share_token"]
    assert edited["updated_at"] == "2026-07-10T12:00:00Z"


def test_get_redirect_info_not_found(monkeypatch):
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: None)

    with pytest.raises(HTTPException) as exc:
        svc.get_redirect_info("missing")
    assert exc.value.status_code == 404


def test_claim_owner_links_unclaimed_folio(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "origin-1",
        "participant_shops": [],
        "pieces": [],
        "customer": None,
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(
        svc,
        "_link_folio_to_customer",
        lambda fid, d, uid, name, phone, gid: {
            "folio": {**d, "customer": {"user_uid": uid, "group_id": gid}},
            "group_id": gid,
            "needs_group": False,
            "user": {"uid": uid},
            "notifications": [],
        },
    )

    result = svc.claim_owner("fid", "uid-1", "group-buyer", "Taller", "555")

    assert result["claimed"] is True
    assert result["group_id"] == "group-buyer"


def test_claim_owner_idempotent_same_group(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": {"user_uid": "uid-1", "group_id": "group-buyer"},
        "pieces": [],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)

    result = svc.claim_owner("fid", "uid-1", "group-buyer")

    assert result["claimed"] is False
    assert result["group_id"] == "group-buyer"


def test_claim_owner_rejects_claimed_by_other(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": {"user_uid": "other-uid", "group_id": "other-group"},
        "pieces": [],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)

    with pytest.raises(HTTPException) as exc:
        svc.claim_owner("fid", "uid-1", "group-buyer")
    assert exc.value.status_code == 409


def test_claim_account_rejects_claimed_by_other(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": {"user_uid": "other-uid", "group_id": "other-group"},
        "pieces": [],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_ensure_platform_user", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_resolve_existing_group_id", lambda uid, t: "group-buyer")

    with pytest.raises(HTTPException) as exc:
        svc.claim_account("fid", "uid-1", "Buyer", "555", None)
    assert exc.value.status_code == 409


def test_claim_guest_links_unclaimed_folio(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": None,
        "pieces": [],
    }
    edited = {}

    def fake_edit(fid, data):
        edited.update(data)
        return {**doc, **data}

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: {**doc, **edited} if edited else doc)
    monkeypatch.setattr(svc.folioRepository, "edit", fake_edit)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")

    result = svc.claim_guest("fid", "device-abc")

    assert result["claimed"] is True
    assert edited["customer"]["user_uid"] == "device-abc"
    assert edited["customer"]["type"] == "guest"


def test_claim_guest_idempotent_same_device(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": {"type": "guest", "user_uid": "device-abc"},
        "pieces": [],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)

    result = svc.claim_guest("fid", "device-abc")

    assert result["claimed"] is False


def test_claim_guest_rejects_claimed_by_other(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": {"type": "guest", "user_uid": "other-device"},
        "pieces": [],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)

    with pytest.raises(HTTPException) as exc:
        svc.claim_guest("fid", "device-abc")
    assert exc.value.status_code == 409


def test_claim_owner_requires_group_id(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        svc.claim_owner("fid", "uid-1", "")
    assert exc.value.status_code == 400


def test_finish_claim_allows_reassign_from_guest_claim(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": {"type": "guest", "user_uid": "device-abc"},
        "pieces": [],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(
        svc,
        "_link_folio_to_customer",
        lambda fid, d, uid, name, phone, gid: {
            "folio": {**d, "customer": {"type": "eassymo", "user_uid": uid, "group_id": gid}},
            "group_id": gid,
            "needs_group": False,
            "user": {"uid": uid},
            "notifications": [],
        },
    )

    with patch("app.repositories.UserRepository.find_one", return_value={"name": "Buyer", "phone": "555"}):
        result = svc.finish_claim("fid", "uid-real", "group-buyer", "buyer")

    assert result["group_id"] == "group-buyer"
    assert result["folio"]["customer"]["user_uid"] == "uid-real"


def test_finish_claim_still_rejects_claim_by_real_owner(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": {
            "type": "eassymo",
            "user_uid": "other-uid",
            "group_id": "other-group",
        },
        "pieces": [],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)

    with patch("app.repositories.UserRepository.find_one", return_value={"name": "Buyer", "phone": "555"}):
        with pytest.raises(HTTPException) as exc:
            svc.finish_claim("fid", "uid-real", "group-buyer", "buyer")
    assert exc.value.status_code == 409


def test_claim_account_allows_reassign_from_guest_claim_with_group(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": {"type": "guest", "user_uid": "device-abc"},
        "pieces": [],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc, "_ensure_platform_user", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_resolve_existing_group_id", lambda uid, t: "group-buyer")
    monkeypatch.setattr(
        svc,
        "_link_folio_to_customer",
        lambda fid, d, uid, name, phone, gid: {
            "folio": {**d, "customer": {"type": "eassymo", "user_uid": uid, "group_id": gid}},
            "group_id": gid,
            "needs_group": False,
            "user": {"uid": uid},
            "notifications": [],
        },
    )

    result = svc.claim_account("fid", "uid-real", "Buyer", "555", None)

    assert result["group_id"] == "group-buyer"
    assert result["folio"]["customer"]["user_uid"] == "uid-real"


def test_claim_account_allows_reassign_from_guest_claim_needs_group(monkeypatch):
    doc = {
        "_id": "fid",
        "customer": {"type": "guest", "user_uid": "device-abc"},
        "pieces": [],
    }
    edited = {}

    def fake_edit(fid, data):
        edited.update(data)
        return {**doc, **data}

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: {**doc, **edited} if edited else doc)
    monkeypatch.setattr(svc.folioRepository, "edit", fake_edit)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")
    monkeypatch.setattr(svc, "_ensure_platform_user", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_resolve_existing_group_id", lambda uid, t: None)

    with patch("app.services.UserService.get_user_with_groups", return_value={"uid": "uid-real", "groups": []}):
        result = svc.claim_account("fid", "uid-real", "Buyer", "555", None)

    assert result["needs_group"] is True
    assert result["group_id"] is None
    assert edited["customer"]["type"] == "eassymo"
    assert edited["customer"]["user_uid"] == "uid-real"


def test_update_pieces_allows_open_piece_options_after_partial_order(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "shop-a",
        "pieces": [
            {
                "piece_id": "p-ordered",
                "name": "Balata",
                "status": "cotizada",
                "options": [{"brand": "Bosch", "code": "1", "price": 100, "source_shop_id": "shop-a"}],
                "order": {"option_index": 0, "status": "ordenada"},
            },
            {
                "piece_id": "p-open",
                "name": "Filtro",
                "status": "pendiente",
                "options": [],
            },
        ],
    }
    saved = {}

    def fake_set_pieces(fid, pieces, updated_at):
        saved["pieces"] = pieces
        return {**doc, "pieces": pieces, "updated_at": updated_at}

    monkeypatch.setattr(
        svc.folioRepository,
        "find_by_id",
        lambda fid: {**doc, "pieces": saved.get("pieces", doc["pieces"])},
    )
    monkeypatch.setattr(svc.folioRepository, "set_pieces", fake_set_pieces)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")
    monkeypatch.setattr(svc, "sync_assigned_folio", lambda *a, **k: None)

    next_pieces = [
        doc["pieces"][0],
        {
            **doc["pieces"][1],
            "options": [{"brand": "Mann", "code": "2", "price": 50, "source_shop_id": "shop-a", "ready": True}],
            "status": "cotizada",
        },
    ]

    result = svc.update_pieces("fid", next_pieces)
    assert saved["pieces"][1]["options"][0]["brand"] == "Mann"
    assert result["pieces"][1]["options"][0]["brand"] == "Mann"


def test_update_pieces_rejects_ordered_piece_option_changes(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "shop-a",
        "pieces": [
            {
                "piece_id": "p-ordered",
                "name": "Balata",
                "status": "cotizada",
                "options": [{"brand": "Bosch", "code": "1", "price": 100, "source_shop_id": "shop-a"}],
                "order": {"option_index": 0, "status": "ordenada"},
            },
        ],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)

    tampered = [
        {
            **doc["pieces"][0],
            "options": [{"brand": "Changed", "code": "1", "price": 100, "source_shop_id": "shop-a"}],
        }
    ]

    with pytest.raises(HTTPException) as exc:
        svc.update_pieces("fid", tampered)
    assert exc.value.status_code == 403


def test_submit_shop_options_rejects_ordered_piece(monkeypatch):
    doc = {
        "_id": "fid",
        "origin_group_id": "shop-a",
        "pieces": [
            {
                "piece_id": "p-ordered",
                "name": "Balata",
                "options": [],
                "order": {"option_index": 0, "status": "ordenada"},
            },
        ],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)

    with pytest.raises(HTTPException) as exc:
        svc.submit_shop_options("fid", "p-ordered", [{"brand": "X", "code": "1", "price": 1}], "shop-a", "Shop")
    assert exc.value.status_code == 403


def test_merge_piece_options_dedupes_duplicate_bids(monkeypatch):
    doc = {
        "_id": "fid",
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Filtro",
                "options": [{"brand": "Old", "code": "9", "price": 1, "source_shop_id": "shop-a"}],
            }
        ],
    }
    saved = {}

    def fake_set_piece_options(fid, piece_id, options, status, updated_at):
        saved["options"] = options
        return {**doc, "pieces": [{**doc["pieces"][0], "options": options, "status": status}]}

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc.folioRepository, "set_piece_options", fake_set_piece_options)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")
    monkeypatch.setattr(svc, "sync_assigned_folio", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_append_activity_log", lambda *a, **k: None)

    svc._merge_piece_options(
        doc,
        "fid",
        "p1",
        [
            {"brand": "Mann", "code": "1", "price": 12},
            {"brand": "Mann", "code": "1", "price": 15},
            {"brand": "Bosch", "code": "2", "price": 20},
        ],
        "shop-a",
        "Shop A",
    )

    brands = [o["brand"] for o in saved["options"]]
    assert brands == ["Mann", "Bosch"]
    assert len(saved["options"]) == 2


def test_order_piece_persists_domicilio_address(monkeypatch):
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
    saved_order = {}

    def fake_set_piece_order(fid, piece_id, order, updated_at):
        saved_order.update(order)
        return {**doc, "pieces": [{**doc["pieces"][0], "order": order}]}

    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)
    monkeypatch.setattr(svc.folioRepository, "set_piece_order", fake_set_piece_order)
    monkeypatch.setattr(svc, "_hydrate", lambda d: d)
    monkeypatch.setattr(svc, "_now", lambda: "2026-07-10T12:00:00Z")
    monkeypatch.setattr(svc, "sync_assigned_folio", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_ensure_mostrador_orders_materialized", lambda *a, **k: None)

    address = {"address": "Calle 1", "lat": 19.4, "lng": -99.1}
    contact = {"name": "Juan", "phone": "5551234567"}

    svc.order_piece("fid", "p1", 0, "domicilio", address, contact)

    assert saved_order["delivery_mode"] == "domicilio"
    assert saved_order["delivery_address"]["address"] == "Calle 1"
    assert saved_order["delivery_contact"]["name"] == "Juan"


def test_order_piece_requires_domicilio_address(monkeypatch):
    doc = {
        "_id": "fid",
        "pieces": [
            {
                "piece_id": "p1",
                "options": [{"brand": "Mann", "code": "1", "price": 50, "ready": True}],
            }
        ],
    }
    monkeypatch.setattr(svc.folioRepository, "find_by_id", lambda fid: doc)

    with pytest.raises(HTTPException) as exc:
        svc.order_piece("fid", "p1", 0, "domicilio")
    assert exc.value.status_code == 400
