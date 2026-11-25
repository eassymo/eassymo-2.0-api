from datetime import datetime, timezone
from unittest.mock import patch

from app.services import SellerReachService as svc
from app.services.SellerReachService import Limits, SellerReachError
from app.utils.ResponseUtils import get_unsuccessful_response

GLOBAL = {"wide_threshold": 50, "wide_per_day": 2, "capped_max": 20, "enforcement": "shadow"}


def _utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_limits_for_override_wins():
    with patch.object(svc.repo, "get_settings", return_value=GLOBAL), patch.object(
        svc.repo, "get_override", return_value={"group_id": "g", "capped_max": 30}
    ):
        assert svc.limits_for("g") == Limits(50, 2, 30, False)


def test_limits_for_override_enforcement_and_none():
    with patch.object(svc.repo, "get_settings", return_value=GLOBAL), patch.object(svc.repo, "get_override", return_value=None):
        assert svc.limits_for("g").enforce is False
    with patch.object(svc.repo, "get_settings", return_value=GLOBAL), patch.object(
        svc.repo, "get_override", return_value={"enforcement": "enforce"}
    ):
        assert svc.limits_for("g").enforce is True


def test_local_day_rolls_at_mexico_midnight():
    assert svc.local_day(_utc("2026-11-26T05:59:00Z")) == "2026-11-25"
    assert svc.local_day(_utc("2026-11-26T06:00:00Z")) == "2026-11-26"


def test_renews_at_is_next_local_midnight():
    r = svc.renews_at(_utc("2026-11-25T18:00:00Z"))
    assert r.utcoffset() is not None
    assert r.astimezone(timezone.utc) == _utc("2026-11-26T06:00:00Z")


def test_audience_unions_followers_and_dedupes():
    assert svc.audience(["a", "b", ""], ["b", "c"]) == 3
    assert svc.audience(["a"], None) == 1


def test_today_shape():
    now = _utc("2026-11-25T18:00:00Z")
    with patch.object(svc.repo, "get_settings", return_value=GLOBAL), patch.object(
        svc.repo, "get_override", return_value=None
    ), patch.object(svc.repo, "get_usage", return_value={"wide_used": 3, "wide_request_ids": []}):
        t = svc.today("g", now)
    assert t == {
        "day": "2026-11-25",
        "wide_used": 3,
        "wide_per_day": 2,
        "wide_left": 0,
        "wide_threshold": 50,
        "capped_max": 20,
        "renews_at": "2026-11-26T06:00:00+00:00",
        "enforcement": "shadow",
    }


def test_error_response_carries_code_and_data():
    err = SellerReachError("request_full", "Esta solicitud ya está llena.", {"full_ids": ["x"]})
    assert err.status_code == 409
    assert get_unsuccessful_response(err) == {
        "error": "Esta solicitud ya está llena.",
        "code": "request_full",
        "data": {"full_ids": ["x"]},
    }


# --- decide ---------------------------------------------------------------

import threading
from contextlib import contextmanager

import pytest

NOW = _utc("2026-11-25T18:00:00Z")
SHADOW = Limits(50, 2, 20, False)
ENFORCE = Limits(50, 2, 20, True)


@contextmanager
def _decide_env(limits=ENFORCE, reserve="reserved", used=0):
    with patch.object(svc, "limits_for", return_value=limits), patch.object(
        svc.repo, "try_reserve_wide", return_value=reserve
    ) as reserve_mock, patch.object(
        svc.repo, "get_usage", return_value={"wide_used": used, "wide_request_ids": []}
    ), patch.object(svc.repo, "write_event") as events:
        yield reserve_mock, events


def _kinds(events):
    return [c.args[0] for c in events.call_args_list]


def test_decide_wide_reserves_slot():
    with _decide_env(reserve="reserved") as (reserve, events):
        out = svc.decide("g", "r1", 64, 0, None, NOW)
    assert out == {"tier": "wide", "day": "2026-11-25", "audience": 64}
    reserve.assert_called_once_with("g", "2026-11-25", "r1", 2)
    assert _kinds(events) == ["wide_reserved"]


def test_decide_already_reserved_is_wide_without_new_event():
    with _decide_env(reserve="already_reserved") as (_, events):
        assert svc.decide("g", "r1", 64, 64, "wide_pending", NOW)["tier"] == "wide"
    assert _kinds(events) == []


def test_decide_already_wide_never_limited():
    with _decide_env(used=2) as (reserve, events):
        out = svc.decide("g", "r1", 300, 60, "wide", NOW)
    assert out["tier"] == "wide"
    reserve.assert_not_called()
    assert _kinds(events) == []


def test_decide_mid_range_with_slots_is_normal():
    with _decide_env(used=1) as (reserve, events):
        out = svc.decide("g", "r1", 35, 0, None, NOW)
    assert out == {"tier": "normal", "day": "2026-11-25", "audience": 35}
    reserve.assert_not_called()
    assert _kinds(events) == []


def test_decide_exhausted_refuses_over_20():
    with _decide_env(used=2) as (_, events):
        with pytest.raises(SellerReachError) as exc:
            svc.decide("g", "r1", 21, 0, None, NOW)
    err = exc.value
    assert err.code == "seller_cap_exceeded"
    assert err.status_code == 409
    assert err.message == "Hoy ya usaste tus 2 envíos a 50 tiendas o más. Esta pieza puede llegar a 20 tiendas como máximo."
    assert err.data == {
        "request_id": "r1",
        "audience": 21,
        "max_allowed": 20,
        "wide_left": 0,
        "renews_at": "2026-11-26T06:00:00+00:00",
    }
    assert _kinds(events) == ["refused"]


def test_decide_wide_audience_exhausted_refuses():
    with _decide_env(reserve="exhausted", used=2) as (_, events):
        with pytest.raises(SellerReachError):
            svc.decide("g", "r1", 64, 0, None, NOW)
    assert _kinds(events) == ["refused"]


def test_decide_exhausted_allows_20_as_capped():
    with _decide_env(used=2) as (_, events):
        out = svc.decide("g", "r1", 20, 0, None, NOW)
    assert out == {"tier": "capped", "day": "2026-11-25", "audience": 20}
    assert _kinds(events) == ["capped"]


def test_decide_shadow_never_refuses():
    with _decide_env(limits=SHADOW, used=2) as (_, events):
        out = svc.decide("g", "r1", 21, 0, None, NOW)
    assert out["tier"] == "capped"
    assert "would_block" in _kinds(events)
    assert "refused" not in _kinds(events)


def test_decide_shadow_still_reserves():
    with _decide_env(limits=SHADOW, reserve="reserved") as (reserve, _):
        assert svc.decide("g", "r1", 64, 0, None, NOW)["tier"] == "wide"
    reserve.assert_called_once()


def test_decide_existing_above_20_cannot_grow():
    with _decide_env(used=2):
        with pytest.raises(SellerReachError):
            svc.decide("g", "r1", 31, 30, "capped", NOW)
    with _decide_env(used=2) as (_, events):
        out = svc.decide("g", "r1", 30, 30, "capped", NOW)
    assert out["tier"] == "capped"
    assert _kinds(events) == []


def test_decide_uses_today_not_creation_day():
    after_midnight = _utc("2026-11-26T06:01:00Z")
    with _decide_env(reserve="reserved") as (reserve, _):
        out = svc.decide("g", "r1", 64, 0, None, after_midnight)
    assert out["day"] == "2026-11-26"
    assert reserve.call_args.args[1] == "2026-11-26"


class _FakeUsage:
    """Just enough of a Mongo collection for try_reserve_wide, atomic under a lock."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.lock = threading.Lock()

    def _matches(self, doc, flt):
        for key, cond in flt.items():
            val = doc.get(key)
            if isinstance(cond, dict):
                if "$lt" in cond and not val < cond["$lt"]:
                    return False
                if "$ne" in cond and (cond["$ne"] in val if isinstance(val, list) else val == cond["$ne"]):
                    return False
            elif isinstance(val, list):
                if cond not in val:
                    return False
            elif val != cond:
                return False
        return True

    def update_one(self, flt, update, upsert=False):
        with self.lock:
            if not any(self._matches(d, flt) for d in self.docs) and upsert:
                self.docs.append({**flt, **update.get("$setOnInsert", {})})

    def find_one_and_update(self, flt, update):
        with self.lock:
            for d in self.docs:
                if self._matches(d, flt):
                    before = {**d, "wide_request_ids": list(d["wide_request_ids"])}
                    for k, v in update.get("$inc", {}).items():
                        d[k] = d.get(k, 0) + v
                    for k, v in update.get("$push", {}).items():
                        d.setdefault(k, []).append(v)
                    return before
            return None

    def find_one(self, flt):
        with self.lock:
            return next((dict(d) for d in self.docs if self._matches(d, flt)), None)


def test_two_concurrent_reservations_one_slot():
    fake = _FakeUsage([{"group_id": "g", "day": "2026-11-25", "wide_used": 1, "wide_request_ids": ["r0"]}])
    barrier = threading.Barrier(2)
    results, errors = [], []

    def run(request_id):
        barrier.wait()
        try:
            results.append(svc.decide("g", request_id, 60, 0, None, NOW))
        except SellerReachError as e:
            errors.append(e)

    with patch.object(svc, "limits_for", return_value=ENFORCE), patch.object(
        svc.repo, "_usage", return_value=fake
    ), patch.object(svc.repo, "ensure_indexes"), patch.object(svc.repo, "write_event"):
        threads = [threading.Thread(target=run, args=(r,)) for r in ("r1", "r2")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert [r["tier"] for r in results] == ["wide"]
    assert len(errors) == 1 and errors[0].data["wide_left"] == 0
    assert fake.docs[0]["wide_used"] == 2
