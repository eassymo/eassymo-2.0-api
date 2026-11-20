from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.WhatsappUsage import TierIn
from app.services.whatsapp_usage_math import (
    percent_used,
    seller_cap,
    usage_state,
    window_end,
    window_expired,
)

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def test_window_end_adds_seconds():
    assert window_end(T0, 8 * 3600) == T0 + timedelta(hours=8)


def test_window_expired_at_exact_boundary_is_true():
    assert window_expired(T0, 3600, T0 + timedelta(seconds=3600)) is True
    assert window_expired(T0, 3600, T0 + timedelta(seconds=3599)) is False


def test_window_expired_none_is_true():
    assert window_expired(None, 3600, T0) is True


def test_percent_used_takes_larger_ratio():
    assert percent_used(10, 50, 270_000, 300_000) == 90


def test_percent_used_clamps_at_100_when_over_limit():
    assert percent_used(70, 50, 0, 300_000) == 100


def test_percent_used_zero_limit_is_100():
    assert percent_used(0, 0, 0, 300_000) == 100


def test_seller_cap_floor_min_one():
    assert seller_cap(3, 10) == 1
    assert seller_cap(50, 30) == 15


def test_seller_cap_none_when_off():
    assert seller_cap(50, None) is None


def test_usage_state_shadow_wins_over_limit():
    assert usage_state(100, 80, "shadow", True) == "shadow"
    assert usage_state(100, 80, "enforce", True) == "limit"
    assert usage_state(80, 80, "enforce", False) == "warning"
    assert usage_state(10, 80, "enforce", False) == "ok"


def _tier(**over):
    data = dict(
        name="normal",
        solicitudes_per_window=50,
        window_seconds=3600,
        token_ceiling_per_window=300_000,
        burst_messages_per_minute=10,
        warn_at_percent=80,
        enforcement="shadow",
    )
    data.update(over)
    return TierIn(**data)


def test_tier_in_rejects_window_under_one_hour():
    assert _tier().window_seconds == 3600
    with pytest.raises(ValidationError):
        _tier(window_seconds=3599)


@pytest.mark.parametrize(
    "used,limit,expected",
    [(29, 100, 29), (57, 100, 57), (58, 100, 58), (87, 300, 29)],
)
def test_percent_used_exact_integer_ratios(used, limit, expected):
    assert percent_used(used, limit, 0, 300_000) == expected


def test_percent_used_ignores_non_positive_token_ceiling():
    assert percent_used(10, 50, 999_999, 0) == 20
    assert percent_used(10, 50, 999_999, -5) == 20
