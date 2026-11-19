from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId

from app.repositories import WhatsappInboundRepository as inbound_repo
from app.repositories import WhatsappUsageRepository as repo

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
WS = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)


# --- Grants ---------------------------------------------------------------

def test_add_grant_inserts_for_window_and_returns_doc():
    col = MagicMock()
    with patch.object(repo, "_grants", return_value=col):
        out = repo.add_grant("g1", 10, "promo", "admin1", WS)
    doc = col.insert_one.call_args[0][0]
    assert doc["group_id"] == "g1"
    assert doc["amount"] == 10
    assert doc["reason"] == "promo"
    assert doc["granted_by"] == "admin1"
    assert doc["window_start"] == WS
    assert "created_at" in doc
    assert out["amount"] == 10 and "_id" not in out


def test_sum_grants_matches_exact_window():
    col = MagicMock()
    col.aggregate.return_value = [{"_id": None, "total": 15}]
    with patch.object(repo, "_grants", return_value=col):
        assert repo.sum_grants("g1", WS) == 15
    pipeline = col.aggregate.call_args[0][0]
    assert pipeline[0] == {"$match": {"group_id": "g1", "window_start": WS}}


def test_sum_grants_none_window_sums_pending_and_empty_is_zero():
    col = MagicMock()
    col.aggregate.return_value = []
    with patch.object(repo, "_grants", return_value=col):
        assert repo.sum_grants("g1", None) == 0
    pipeline = col.aggregate.call_args[0][0]
    assert pipeline[0] == {"$match": {"group_id": "g1", "window_start": None}}


def test_bind_pending_grants_moves_pending_into_window():
    col = MagicMock()
    col.update_many.return_value = MagicMock(modified_count=2)
    with patch.object(repo, "_grants", return_value=col):
        assert repo.bind_pending_grants("g1", WS) == 2
    flt, update = col.update_many.call_args[0]
    assert flt == {"group_id": "g1", "window_start": None}
    assert update == {"$set": {"window_start": WS}}


def test_list_grants_for_window():
    col = MagicMock()
    col.find.return_value.sort.return_value = [{"_id": ObjectId(), "amount": 3}]
    with patch.object(repo, "_grants", return_value=col):
        out = repo.list_grants("g1", WS)
    assert col.find.call_args[0][0] == {"group_id": "g1", "window_start": WS}
    assert out == [{"amount": 3}]


# --- Credit requests --------------------------------------------------------

def test_create_credit_request_is_pending_with_string_id():
    col = MagicMock()
    oid = ObjectId()
    col.insert_one.return_value = MagicMock(inserted_id=oid)
    with patch.object(repo, "_requests", return_value=col):
        out = repo.create_credit_request("g1", "u1", "need more")
    doc = col.insert_one.call_args[0][0]
    assert doc["status"] == "pending"
    assert doc["requested_by"] == "u1"
    assert doc["note"] == "need more"
    assert doc["resolved_by"] is None
    assert out["id"] == str(oid) and "_id" not in out


def test_find_pending_credit_request():
    col = MagicMock()
    oid = ObjectId()
    col.find_one.return_value = {"_id": oid, "group_id": "g1", "status": "pending"}
    with patch.object(repo, "_requests", return_value=col):
        out = repo.find_pending_credit_request("g1")
    assert col.find_one.call_args[0][0] == {"group_id": "g1", "status": "pending"}
    assert out["id"] == str(oid)


def test_list_credit_requests_filters_by_status():
    col = MagicMock()
    oid = ObjectId()
    col.find.return_value.sort.return_value = [{"_id": oid, "status": "pending"}]
    with patch.object(repo, "_requests", return_value=col):
        out = repo.list_credit_requests("pending")
    assert col.find.call_args[0][0] == {"status": "pending"}
    assert out == [{"id": str(oid), "status": "pending"}]


def test_list_credit_requests_without_status_lists_all():
    col = MagicMock()
    col.find.return_value.sort.return_value = []
    with patch.object(repo, "_requests", return_value=col):
        assert repo.list_credit_requests(None) == []
    assert col.find.call_args[0][0] == {}


def test_resolve_credit_request_only_from_pending():
    col = MagicMock()
    oid = ObjectId()
    col.find_one_and_update.return_value = {"_id": oid, "status": "granted", "resolved_by": "admin1"}
    with patch.object(repo, "_requests", return_value=col):
        out = repo.resolve_credit_request(str(oid), "granted", "admin1")
    flt, update = col.find_one_and_update.call_args[0][:2]
    assert flt == {"_id": oid, "status": "pending"}
    assert update["$set"]["status"] == "granted"
    assert update["$set"]["resolved_by"] == "admin1"
    assert "resolved_at" in update["$set"]
    assert out["id"] == str(oid)


def test_resolve_credit_request_bad_id_returns_none():
    col = MagicMock()
    with patch.object(repo, "_requests", return_value=col):
        assert repo.resolve_credit_request("not-an-id", "declined", "admin1") is None
    col.find_one_and_update.assert_not_called()


# --- Aggregates -----------------------------------------------------------

def test_aggregate_usage_shapes_facets():
    col = MagicMock()
    col.aggregate.return_value = [
        {
            "totals": [{"_id": None, "solicitudes": 4, "tokens": 9000, "estimated_cost": 0.5}],
            "by_day": [{"_id": "2026-11-18", "solicitudes": 4, "tokens": 9000, "estimated_cost": 0.5}],
            "top_stores": [{"_id": "g1", "solicitudes": 4, "tokens": 9000, "estimated_cost": 0.5}],
        }
    ]
    since, until = NOW - timedelta(days=7), NOW
    with patch.object(repo, "_events", return_value=col):
        out = repo.aggregate_usage(since, until)
    pipeline = col.aggregate.call_args[0][0]
    assert pipeline[0] == {"$match": {"created_at": {"$gte": since, "$lt": until}}}
    assert out["totals"] == {"solicitudes": 4, "tokens": 9000, "estimated_cost": 0.5}
    assert out["by_day"] == [{"day": "2026-11-18", "solicitudes": 4, "tokens": 9000, "estimated_cost": 0.5}]
    assert out["top_stores"] == [{"group_id": "g1", "solicitudes": 4, "tokens": 9000, "estimated_cost": 0.5}]


def test_aggregate_usage_empty_returns_zero_totals():
    col = MagicMock()
    col.aggregate.return_value = [{"totals": [], "by_day": [], "top_stores": []}]
    with patch.object(repo, "_events", return_value=col):
        out = repo.aggregate_usage(NOW - timedelta(days=1), NOW)
    assert out == {"totals": {"solicitudes": 0, "tokens": 0, "estimated_cost": 0.0}, "by_day": [], "top_stores": []}


def test_iter_events_streams_range_in_order():
    col = MagicMock()
    col.find.return_value.sort.return_value = iter([{"event_id": "b1:0"}, {"event_id": "b1:1"}])
    since, until = NOW - timedelta(days=1), NOW
    with patch.object(repo, "_events", return_value=col):
        out = list(repo.iter_events(since, until))
    flt, proj = col.find.call_args[0]
    assert flt == {"created_at": {"$gte": since, "$lt": until}}
    assert proj == {"_id": 0}
    assert [e["event_id"] for e in out] == ["b1:0", "b1:1"]


def test_by_seller_merges_counter_and_event_tokens():
    usage_col = MagicMock()
    usage_col.find_one.return_value = {"group_id": "g1", "window_start": WS, "by_uid": {"u1": 3, "u2": 1, "u3": 0}}
    events_col = MagicMock()
    events_col.aggregate.return_value = [{"_id": "u1", "tokens": 5000}, {"_id": "u4", "tokens": 700}]
    with patch.object(repo, "_usage", return_value=usage_col), patch.object(repo, "_events", return_value=events_col):
        out = repo.by_seller("g1")
    match = events_col.aggregate.call_args[0][0][0]["$match"]
    assert match == {"group_id": "g1", "created_at": {"$gte": WS}}
    assert out == [
        {"uid": "u1", "solicitudes": 3, "tokens": 5000},
        {"uid": "u2", "solicitudes": 1, "tokens": 0},
        {"uid": "u4", "solicitudes": 0, "tokens": 700},
    ]


def test_by_seller_without_usage_doc_is_empty():
    usage_col = MagicMock()
    usage_col.find_one.return_value = None
    with patch.object(repo, "_usage", return_value=usage_col):
        assert repo.by_seller("g1") == []


# --- Inbound: count_recent --------------------------------------------------

def test_count_recent_counts_inbound_from_phone_in_window():
    col = MagicMock()
    col.count_documents.return_value = 7
    with patch.object(inbound_repo, "_col", return_value=col):
        assert inbound_repo.count_recent("+5215555", 60, NOW) == 7
    flt = col.count_documents.call_args[0][0]
    assert flt == {
        "from_number": "+5215555",
        "created_at": {"$gte": NOW - timedelta(seconds=60)},
        "direction": {"$ne": "outbound"},
    }


def test_count_recent_empty_phone_is_zero():
    col = MagicMock()
    with patch.object(inbound_repo, "_col", return_value=col):
        assert inbound_repo.count_recent("", 60, NOW) == 0
    col.count_documents.assert_not_called()


# --- list_active_usage / get_credit_request ---------------------------------

def _active_cols(settings, usage_docs, grants=()):
    tiers = MagicMock()
    tiers.find.return_value = [
        {"tier_id": "normal", **repo.NORMAL_TIER_SEED, "enforcement": "enforce"},
        {"tier_id": "shadowy", **repo.NORMAL_TIER_SEED, "enforcement": "shadow"},
    ]
    store_tiers = MagicMock()
    store_tiers.find.return_value = [{"group_id": "gs", "tier_id": "shadowy"}]
    usage = MagicMock()
    usage.find.return_value = usage_docs
    g = MagicMock()
    g.aggregate.return_value = list(grants)
    return tiers, store_tiers, usage, g


def test_list_active_usage_returns_warning_and_limit_sorted_capped_to_active():
    start = NOW - timedelta(hours=1)
    old = NOW - timedelta(hours=9)
    docs = [
        {"group_id": "ok", "window_start": start, "solicitudes_used": 5, "tokens_used": 0},
        {"group_id": "warn", "window_start": start, "solicitudes_used": 45, "tokens_used": 0},
        {"group_id": "full", "window_start": start, "solicitudes_used": 50, "tokens_used": 0},
        {"group_id": "expired", "window_start": old, "solicitudes_used": 50, "tokens_used": 0},
        {"group_id": "gs", "window_start": start, "solicitudes_used": 50, "tokens_used": 0},
        {"group_id": "granted", "window_start": start, "solicitudes_used": 50, "tokens_used": 0},
    ]
    grants = [{"_id": {"group_id": "granted", "window_start": start}, "total": 50}]
    tiers, st, usage, g = _active_cols({}, docs, grants)
    with patch.object(repo, "get_settings", return_value={"enforcement_enabled": True, "shadow_all": False}), \
         patch.object(repo, "_tiers", return_value=tiers), patch.object(repo, "_store_tiers", return_value=st), \
         patch.object(repo, "_usage", return_value=usage), patch.object(repo, "_grants", return_value=g), \
         patch.object(repo, "ensure_indexes"):
        out = repo.list_active_usage(NOW)
    assert [r["group_id"] for r in out] == ["full", "gs", "warn"]
    assert [r["state"] for r in out] == ["limit", "limit", "warning"]
    assert out[0]["percent"] == 100 and out[2]["percent"] == 90
    assert [r["enforcement_mode"] for r in out] == ["enforce", "shadow", "enforce"]


def test_list_active_usage_lists_would_be_state_for_shadow_all_and_kill_switch():
    start = NOW - timedelta(hours=1)
    docs = [{"group_id": "full", "window_start": start, "solicitudes_used": 60, "tokens_used": 0}]
    for settings, mode in (
        ({"enforcement_enabled": True, "shadow_all": True}, "shadow"),
        ({"enforcement_enabled": False, "shadow_all": False}, "off"),
    ):
        tiers, st, usage, g = _active_cols({}, docs)
        with patch.object(repo, "get_settings", return_value=settings), \
             patch.object(repo, "_tiers", return_value=tiers), patch.object(repo, "_store_tiers", return_value=st), \
             patch.object(repo, "_usage", return_value=usage), patch.object(repo, "_grants", return_value=g), \
             patch.object(repo, "ensure_indexes"):
            out = repo.list_active_usage(NOW)
        assert [(r["group_id"], r["state"], r["enforcement_mode"]) for r in out] == [("full", "limit", mode)]


def test_get_credit_request_bad_id_is_none_and_good_id_cleans():
    col = MagicMock()
    oid = ObjectId()
    col.find_one.return_value = {"_id": oid, "group_id": "g1", "status": "pending"}
    with patch.object(repo, "_requests", return_value=col), patch.object(repo, "ensure_indexes"):
        assert repo.get_credit_request("nope") is None
        out = repo.get_credit_request(str(oid))
    assert out["id"] == str(oid) and "_id" not in out


# --- Final-review fixes: solicitudes are distinct counted bursts ----------

def test_refund_marks_burst_events_uncounted():
    usage_col, events_col = MagicMock(), MagicMock()
    with patch.object(repo, "_usage", return_value=usage_col), patch.object(repo, "_events", return_value=events_col):
        repo.refund("g1", "u1", "b1")
    flt, update = events_col.update_many.call_args[0]
    assert flt == {"burst_id": "b1", "counted": True}
    assert update == {"$set": {"counted": False}}


def test_refund_is_idempotent_for_events_even_when_counter_already_released():
    usage_col, events_col = MagicMock(), MagicMock()
    usage_col.update_one.return_value = MagicMock(modified_count=0)
    with patch.object(repo, "_usage", return_value=usage_col), patch.object(repo, "_events", return_value=events_col):
        repo.refund("g1", "u1", "b1")
        repo.refund("g1", "u1", "b1")
    assert events_col.update_many.call_count == 2  # filter on counted:True makes the repeat a no-op


def test_aggregate_usage_counts_distinct_counted_bursts_not_events():
    col = MagicMock()
    col.aggregate.return_value = [{"totals": [], "by_day": [], "top_stores": []}]
    with patch.object(repo, "_events", return_value=col):
        repo.aggregate_usage(NOW - timedelta(days=1), NOW)
    facets = col.aggregate.call_args[0][0][1]["$facet"]
    for name in ("totals", "by_day", "top_stores"):
        stages = facets[name]
        group = next(s["$group"] for s in stages if "$group" in s)
        assert "$addToSet" in group["solicitudes_set"]
        assert "solicitudes" not in group  # no per-event $sum
        add_fields = next(s["$addFields"] for s in stages if "$addFields" in s)
        assert "$size" in str(add_fields["solicitudes"])
        # tokens still add up across every call
        assert "$sum" in group["tokens"]
    top = facets["top_stores"]
    assert top.index(next(s for s in top if "$addFields" in s)) < top.index({"$sort": {"solicitudes": -1, "tokens": -1}})


def test_reopen_credit_request_restores_pending_only_from_given_status():
    col = MagicMock()
    oid = ObjectId()
    with patch.object(repo, "_requests", return_value=col):
        repo.reopen_credit_request(str(oid), "granted")
        repo.reopen_credit_request("not-an-id", "granted")
    flt, update = col.update_one.call_args[0]
    assert flt == {"_id": oid, "status": "granted"}
    assert update == {"$set": {"status": "pending", "resolved_by": None, "resolved_at": None}}
    assert col.update_one.call_count == 1
