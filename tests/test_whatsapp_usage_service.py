import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

import pytest

from app.repositories import WhatsappUsageRepository as real_repo
from app.services.WhatsappUsageService import (
    UsageContext,
    UsageLimitReached,
    UsageSnapshot,
    WhatsappUsageService,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class FakeRepo:
    """In-memory stand-in for WhatsappUsageRepository with the same semantics."""

    NORMAL_TIER_ID = real_repo.NORMAL_TIER_ID
    NORMAL_TIER_SEED = real_repo.NORMAL_TIER_SEED

    def __init__(self, **tier_overrides):
        self.settings = {**real_repo.SETTINGS_DEFAULTS, "shadow_all": False}
        self.tiers = {
            "normal": {**real_repo.NORMAL_TIER_SEED, "tier_id": "normal", "enforcement": "enforce", **tier_overrides}
        }
        self.store_tier = {}
        self.usage = {}
        self.grants = []
        self.events = {}
        self.meter_errors = 0
        self.refunds = []

    # config
    def get_settings(self):
        return dict(self.settings)

    def get_store_tier_id(self, group_id):
        tid = self.store_tier.get(group_id, "normal")
        tier = self.tiers.get(tid)
        return tid if tier and tier.get("active", True) else "normal"

    def get_tier(self, tier_id):
        t = self.tiers.get(tier_id)
        return dict(t) if t else None

    def incr_meter_errors(self):
        self.meter_errors += 1
        return self.meter_errors

    # grants
    def sum_grants(self, group_id, window_start):
        return sum(g["amount"] for g in self.grants if g["group_id"] == group_id and g["window_start"] == window_start)

    def bind_pending_grants(self, group_id, window_start):
        n = 0
        for g in self.grants:
            if g["group_id"] == group_id and g["window_start"] is None:
                g["window_start"] = window_start
                n += 1
        return n

    # counters
    def get_usage(self, group_id):
        doc = self.usage.get(group_id)
        return {**doc, "by_uid": dict(doc["by_uid"]), "reserved_bursts": list(doc["reserved_bursts"])} if doc else None

    def ensure_window(self, group_id, tier_id, window_seconds, now):
        doc = self.usage.get(group_id)
        if doc is None or doc.get("window_start") is None or now >= doc["window_start"] + timedelta(seconds=window_seconds):
            self.usage[group_id] = {
                "group_id": group_id, "tier_id": tier_id, "window_start": now, "solicitudes_used": 0,
                "tokens_used": 0, "by_uid": {}, "reserved_bursts": [], "warned_window": None,
            }
        return self.get_usage(group_id)

    def try_reserve(self, group_id, uid, burst_id, *, limit, token_ceiling, seller_cap, window_start):
        doc = self.usage[group_id]
        if burst_id in doc["reserved_bursts"]:
            return "already_reserved"
        if doc["solicitudes_used"] >= limit:
            return "blocked_quota"
        if doc["tokens_used"] >= token_ceiling:
            return "blocked_tokens"
        if seller_cap is not None and doc["by_uid"].get(uid, 0) >= seller_cap:
            return "blocked_seller_cap"
        doc["solicitudes_used"] += 1
        doc["by_uid"][uid] = doc["by_uid"].get(uid, 0) + 1
        doc["reserved_bursts"].append(burst_id)
        return "reserved"

    def refund(self, group_id, uid, burst_id):
        self.refunds.append(burst_id)
        doc = self.usage.get(group_id)
        if doc and burst_id in doc["reserved_bursts"]:
            doc["solicitudes_used"] -= 1
            doc["by_uid"][uid] -= 1
            doc["reserved_bursts"].remove(burst_id)

    def add_tokens(self, group_id, tokens):
        if tokens > 0 and group_id in self.usage:
            self.usage[group_id]["tokens_used"] += tokens

    def claim_warning(self, group_id, window_start):
        doc = self.usage.get(group_id)
        if doc and doc["window_start"] == window_start and doc["warned_window"] != window_start:
            doc["warned_window"] = window_start
            return True
        return False

    def insert_event(self, event):
        if event["event_id"] in self.events:
            return False
        self.events[event["event_id"]] = dict(event)
        return True

    # helpers for tests
    def seed_usage(self, group_id="g1", used=0, tokens=0, by_uid=None, window_start=NOW - timedelta(hours=1)):
        self.usage[group_id] = {
            "group_id": group_id, "tier_id": "normal", "window_start": window_start, "solicitudes_used": used,
            "tokens_used": tokens, "by_uid": dict(by_uid or {}), "reserved_bursts": [], "warned_window": None,
        }


class FakeInbound:
    def __init__(self, count):
        self.count = count
        self.calls = []

    def count_recent(self, from_number, seconds, now=None):
        self.calls.append((from_number, seconds, now))
        return self.count


def _svc(repo, inbound=None):
    return WhatsappUsageService(repo=repo, inbound=inbound or FakeInbound(0))


def _ctx(burst="b1", uid="u1", group="g1"):
    return UsageContext(group_id=group, uid=uid, burst_id=burst)


# --- limits and grants ------------------------------------------------------

def test_effective_limit_adds_current_window_grants():
    repo = FakeRepo(solicitudes_per_window=10)
    ws = NOW - timedelta(hours=1)
    repo.seed_usage(used=10, window_start=ws)
    repo.grants.append({"group_id": "g1", "amount": 5, "window_start": ws})
    repo.grants.append({"group_id": "g1", "amount": 99, "window_start": ws - timedelta(days=1)})  # expired
    svc = _svc(repo)
    snap = svc.snapshot("g1", now=NOW)
    assert snap.limit == 15
    ctx = _ctx()
    svc.reserve(ctx, now=NOW)  # 10 < 15 so it is allowed
    assert ctx.reserved is True
    assert repo.usage["g1"]["solicitudes_used"] == 11


def test_pending_grant_binds_to_new_window_on_reserve():
    repo = FakeRepo(solicitudes_per_window=1)
    repo.grants.append({"group_id": "g1", "amount": 2, "window_start": None})
    svc = _svc(repo)
    assert svc.snapshot("g1", now=NOW).limit == 3  # shown before any window starts
    for i in range(3):
        svc.reserve(_ctx(burst=f"b{i}"), now=NOW)
    assert repo.usage["g1"]["solicitudes_used"] == 3
    assert repo.grants[0]["window_start"] == NOW
    with pytest.raises(UsageLimitReached):
        svc.reserve(_ctx(burst="b9"), now=NOW)


# --- reserve: enforcement modes ---------------------------------------------

def test_reserve_blocks_in_enforce_mode_and_raises_with_snapshot():
    repo = FakeRepo(solicitudes_per_window=5)
    repo.seed_usage(used=5)
    svc = _svc(repo)
    ctx = _ctx()
    with pytest.raises(UsageLimitReached) as exc:
        svc.reserve(ctx, now=NOW)
    assert exc.value.reason == "quota"
    assert isinstance(exc.value.snapshot, UsageSnapshot)
    assert exc.value.snapshot.used == 5 and exc.value.snapshot.limit == 5
    assert exc.value.snapshot.state == "limit"
    assert ctx.reserved is False
    assert repo.usage["g1"]["solicitudes_used"] == 5


def test_reserve_shadow_mode_never_raises_but_logs_would_block(caplog):
    repo = FakeRepo(solicitudes_per_window=5, enforcement="shadow")
    repo.seed_usage(used=5)
    svc = _svc(repo)
    ctx = _ctx()
    with caplog.at_level(logging.INFO, logger="app.services.WhatsappUsageService"):
        svc.reserve(ctx, now=NOW)
    assert any("would_block" in r.getMessage() for r in caplog.records)
    # still metered so shadow data shows real demand
    assert ctx.reserved is True
    assert repo.usage["g1"]["solicitudes_used"] == 6
    assert ctx.snapshot.state == "shadow"
    assert ctx.crossed_warning is False  # notices suppressed in shadow


def test_reserve_global_kill_switch_never_raises():
    repo = FakeRepo(solicitudes_per_window=5)
    repo.settings["enforcement_enabled"] = False
    repo.seed_usage(used=5)
    svc = _svc(repo)
    ctx = _ctx()
    svc.reserve(ctx, now=NOW)
    assert ctx.reserved is True
    assert ctx.snapshot.enforcement == "shadow"


def test_reserve_shadow_all_overrides_enforce_tier():
    repo = FakeRepo(solicitudes_per_window=5)
    repo.settings["shadow_all"] = True
    repo.seed_usage(used=5)
    svc = _svc(repo)
    ctx = _ctx()
    svc.reserve(ctx, now=NOW)
    assert ctx.reserved is True
    assert ctx.snapshot.state == "shadow"


def test_reserve_sets_crossed_warning_once_when_crossing_80_percent():
    repo = FakeRepo(solicitudes_per_window=10)
    repo.seed_usage(used=7)
    svc = _svc(repo)
    first = _ctx(burst="b1")
    svc.reserve(first, now=NOW)  # 8/10 = 80%
    assert first.crossed_warning is True
    assert first.snapshot.used == 8 and first.snapshot.state == "warning"
    second = _ctx(burst="b2")
    svc.reserve(second, now=NOW)  # 9/10, already warned this window
    assert second.crossed_warning is False


def test_reserve_below_warning_does_not_claim():
    repo = FakeRepo(solicitudes_per_window=10)
    repo.seed_usage(used=1)
    svc = _svc(repo)
    ctx = _ctx()
    svc.reserve(ctx, now=NOW)
    assert ctx.crossed_warning is False
    assert repo.usage["g1"]["warned_window"] is None


def test_reserve_idempotent_for_same_burst():
    repo = FakeRepo(solicitudes_per_window=10)
    svc = _svc(repo)
    svc.reserve(_ctx(burst="b1"), now=NOW)
    again = _ctx(burst="b1")  # webhook retry, fresh context
    svc.reserve(again, now=NOW)
    assert again.reserved is True
    assert repo.usage["g1"]["solicitudes_used"] == 1
    # same context twice is a no-op too
    svc.reserve(again, now=NOW)
    assert repo.usage["g1"]["solicitudes_used"] == 1


def test_lowered_limit_below_usage_blocks_without_error():
    repo = FakeRepo(solicitudes_per_window=50)
    repo.seed_usage(used=40)
    repo.tiers["normal"]["solicitudes_per_window"] = 20  # edited mid-window
    svc = _svc(repo)
    snap = svc.snapshot("g1", now=NOW)
    assert snap.percent == 100 and snap.state == "limit"
    with pytest.raises(UsageLimitReached) as exc:
        svc.reserve(_ctx(), now=NOW)
    assert exc.value.reason == "quota"
    assert repo.meter_errors == 0


def test_tier_missing_falls_back_to_normal():
    repo = FakeRepo(solicitudes_per_window=7)
    repo.store_tier["g1"] = "gone"  # assigned tier row deleted
    svc = _svc(repo)
    snap = svc.snapshot("g1", now=NOW)
    assert snap.tier_id == "normal" and snap.limit == 7
    # even the normal row missing: fall back to the seed values
    repo.tiers.clear()
    snap = svc.snapshot("g1", now=NOW)
    assert snap.tier_id == "normal"
    assert snap.limit == real_repo.NORMAL_TIER_SEED["solicitudes_per_window"]
    ctx = _ctx()
    svc.reserve(ctx, now=NOW)
    assert ctx.reserved is True
    assert repo.meter_errors == 0


def test_per_seller_cap_blocks_that_seller_only():
    repo = FakeRepo(solicitudes_per_window=10, per_seller_cap_percent=30)  # cap = 3
    repo.seed_usage(used=3, by_uid={"u1": 3})
    svc = _svc(repo)
    with pytest.raises(UsageLimitReached) as exc:
        svc.reserve(_ctx(uid="u1", burst="b1"), now=NOW)
    assert exc.value.reason == "seller_cap"
    other = _ctx(uid="u2", burst="b2")
    svc.reserve(other, now=NOW)
    assert other.reserved is True
    assert repo.usage["g1"]["by_uid"] == {"u1": 3, "u2": 1}


def test_reserve_uses_window_of_reread_doc_for_warning():
    """try_reserve may land in a newer window; claim_warning must use that one."""
    repo = FakeRepo(solicitudes_per_window=10)
    repo.seed_usage(used=7)
    newer = NOW - timedelta(minutes=5)
    original = repo.try_reserve

    def reserve_after_reset(group_id, uid, burst_id, **kw):
        repo.seed_usage(used=7, window_start=newer)  # another instance reset the window
        return original(group_id, uid, burst_id, **kw)

    repo.try_reserve = reserve_after_reset
    svc = _svc(repo)
    ctx = _ctx()
    svc.reserve(ctx, now=NOW)
    assert ctx.crossed_warning is True
    assert repo.usage["g1"]["warned_window"] == newer
    assert ctx.snapshot.window_start == newer


# --- follow-ups and tokens ----------------------------------------------------

def test_follow_up_ignores_quota_but_blocks_on_token_ceiling():
    repo = FakeRepo(solicitudes_per_window=5, token_ceiling_per_window=1000)
    repo.seed_usage(used=5, tokens=10)
    svc = _svc(repo)
    ctx = _ctx()
    svc.ensure_tokens_available(ctx, now=NOW)  # quota is full, follow-up still allowed
    assert ctx.reserved is False
    repo.usage["g1"]["tokens_used"] = 1000
    with pytest.raises(UsageLimitReached) as exc:
        svc.ensure_tokens_available(_ctx(), now=NOW)
    assert exc.value.reason == "tokens"


def test_follow_up_token_ceiling_in_shadow_never_raises():
    repo = FakeRepo(token_ceiling_per_window=1000, enforcement="shadow")
    repo.seed_usage(tokens=5000)
    _svc(repo).ensure_tokens_available(_ctx(), now=NOW)


def test_record_call_writes_event_and_adds_tokens():
    repo = FakeRepo()
    repo.settings["price_per_1k_prompt_tokens"] = 0.5
    repo.settings["price_per_1k_completion_tokens"] = 2.0
    repo.seed_usage(used=1)
    svc = _svc(repo)
    ctx = _ctx()
    svc.record_call(ctx, "extract", {"prompt_tokens": 2000, "completion_tokens": 500, "model": "glm-x", "has_usage": True}, counted=True)
    ev = repo.events["b1:0"]
    assert ev["group_id"] == "g1" and ev["uid"] == "u1" and ev["burst_id"] == "b1"
    assert ev["kind"] == "extract" and ev["counted"] is True and ev["status"] == "ok"
    assert ev["prompt_tokens"] == 2000 and ev["completion_tokens"] == 500
    assert ev["model"] == "glm-x"
    assert ev["estimated_cost"] == pytest.approx(2.0)
    assert ev["enforcement_mode"] == "enforce"
    assert ev["tier_id"] == "normal"
    assert ev["usage_missing"] is False
    assert repo.usage["g1"]["tokens_used"] == 2500
    svc.record_call(ctx, "match_answers", {"prompt_tokens": 10, "completion_tokens": 0}, counted=False)
    assert "b1:1" in repo.events
    assert ctx.call_index == 2


def test_record_call_missing_usage_records_zero_and_flags():
    repo = FakeRepo()
    repo.seed_usage()
    svc = _svc(repo)
    ctx = _ctx()
    svc.record_call(ctx, "extract", None, counted=True, model="glm-x")
    ev = repo.events["b1:0"]
    assert ev["prompt_tokens"] == 0 and ev["completion_tokens"] == 0
    assert ev["usage_missing"] is True
    assert ev["model"] == "glm-x"
    svc.record_call(ctx, "extract", {"prompt_tokens": 0, "completion_tokens": 0, "has_usage": False}, counted=False)
    assert repo.events["b1:1"]["usage_missing"] is True
    assert repo.usage["g1"]["tokens_used"] == 0


def test_record_call_duplicate_event_does_not_add_tokens_twice():
    repo = FakeRepo()
    repo.seed_usage()
    svc = _svc(repo)
    svc.record_call(_ctx(), "extract", {"prompt_tokens": 100, "completion_tokens": 0}, counted=True)
    svc.record_call(_ctx(), "extract", {"prompt_tokens": 100, "completion_tokens": 0}, counted=True)  # retry
    assert repo.usage["g1"]["tokens_used"] == 100


# --- refund -------------------------------------------------------------------

def test_refund_noop_when_not_reserved():
    repo = FakeRepo()
    svc = _svc(repo)
    svc.refund(_ctx())
    assert repo.refunds == []


def test_refund_releases_reservation():
    repo = FakeRepo()
    svc = _svc(repo)
    ctx = _ctx()
    svc.reserve(ctx, now=NOW)
    svc.refund(ctx)
    assert repo.refunds == ["b1"]
    assert repo.usage["g1"]["solicitudes_used"] == 0
    assert ctx.reserved is False
    svc.refund(ctx)
    assert repo.refunds == ["b1"]


# --- burst guard ----------------------------------------------------------------

def test_check_burst_guard_blocks_over_limit():
    repo = FakeRepo(burst_messages_per_minute=30)
    inbound = FakeInbound(31)
    svc = _svc(repo, inbound)
    assert svc.check_burst_guard("g1", "+52155", now=NOW) is False
    assert inbound.calls == [("+52155", 60, NOW)]
    inbound.count = 30
    assert svc.check_burst_guard("g1", "+52155", now=NOW) is True


def test_check_burst_guard_shadow_never_blocks():
    repo = FakeRepo(burst_messages_per_minute=30, enforcement="shadow")
    assert _svc(repo, FakeInbound(500)).check_burst_guard("g1", "+52155", now=NOW) is True


# --- fail open --------------------------------------------------------------------

class BrokenRepo(FakeRepo):
    def _boom(self, *a, **kw):
        raise RuntimeError("mongo down")

    ensure_window = _boom
    get_usage = _boom
    insert_event = _boom
    refund = _boom


def test_mongo_error_fails_open_and_counts_error(caplog):
    repo = BrokenRepo(solicitudes_per_window=5)
    svc = _svc(repo)
    ctx = _ctx()
    with caplog.at_level(logging.WARNING, logger="app.services.WhatsappUsageService"):
        svc.reserve(ctx, now=NOW)  # no raise
    assert any("whatsapp_usage_error" in r.getMessage() for r in caplog.records)
    assert repo.meter_errors == 1
    snap = svc.snapshot("g1", now=NOW)
    assert isinstance(snap, UsageSnapshot) and snap.state == "shadow"
    svc.ensure_tokens_available(_ctx(), now=NOW)
    svc.record_call(_ctx(), "extract", {"prompt_tokens": 1}, counted=True)
    ctx.reserved = True
    svc.refund(ctx)
    assert repo.meter_errors == 5


def test_try_reserve_runtime_error_fails_open():
    repo = FakeRepo()

    def raise_contention(*a, **kw):
        raise RuntimeError("whatsapp_usage: reserve contention")

    repo.try_reserve = raise_contention
    svc = _svc(repo)
    ctx = _ctx()
    svc.reserve(ctx, now=NOW)
    assert ctx.reserved is False
    assert repo.meter_errors == 1


def test_burst_guard_error_allows():
    class BadInbound:
        def count_recent(self, *a, **kw):
            raise RuntimeError("boom")

    repo = FakeRepo()
    assert _svc(repo, BadInbound()).check_burst_guard("g1", "+52155", now=NOW) is True
    assert repo.meter_errors == 1


def test_error_counter_failure_is_swallowed():
    class VeryBroken(BrokenRepo):
        def incr_meter_errors(self):
            raise RuntimeError("still down")

    svc = _svc(VeryBroken())
    svc.reserve(_ctx(), now=NOW)  # must not raise


# --- snapshot -----------------------------------------------------------------------

def test_snapshot_without_window_is_fresh():
    repo = FakeRepo(solicitudes_per_window=50, window_seconds=28800)
    snap = _svc(repo).snapshot("g1", now=NOW)
    assert snap.used == 0 and snap.tokens_used == 0 and snap.percent == 0
    assert snap.window_start is None and snap.window_end is None
    assert snap.window_seconds == 28800
    assert snap.state == "ok" and snap.enforcement == "enforce"


def test_snapshot_expired_window_reads_as_fresh():
    repo = FakeRepo(solicitudes_per_window=10, window_seconds=3600)
    repo.seed_usage(used=10, window_start=NOW - timedelta(hours=2))
    snap = _svc(repo).snapshot("g1", now=NOW)
    assert snap.used == 0 and snap.state == "ok" and snap.window_start is None


def test_snapshot_active_window_has_end():
    repo = FakeRepo(solicitudes_per_window=10, window_seconds=3600)
    ws = NOW - timedelta(minutes=30)
    repo.seed_usage(used=3, window_start=ws)
    snap = _svc(repo).snapshot("g1", now=NOW)
    assert snap.window_start == ws and snap.window_end == ws + timedelta(seconds=3600)
    assert snap.used == 3 and snap.percent == 30 and snap.tier_name == "Normal"


def test_snapshot_with_uid_reports_seller_cap_as_limit():
    repo = FakeRepo(solicitudes_per_window=10, per_seller_cap_percent=30)
    repo.seed_usage(used=3, by_uid={"u1": 3})
    svc = _svc(repo)
    assert svc.snapshot("g1", uid="u1", now=NOW).state == "limit"
    assert svc.snapshot("g1", uid="u2", now=NOW).state == "ok"
