"""Pure window and percentage math for WhatsApp usage limits. No I/O."""

import math
from datetime import datetime, timedelta
from typing import Literal, Optional

MIN_WINDOW_SECONDS = 3600


def window_end(window_start: datetime, window_seconds: int) -> datetime:
    return window_start + timedelta(seconds=window_seconds)


def window_expired(window_start: Optional[datetime], window_seconds: int, now: datetime) -> bool:
    if window_start is None:
        return True
    return now >= window_end(window_start, window_seconds)


def effective_limit(tier_limit: int, grant_total: int) -> int:
    return tier_limit + grant_total


def percent_used(used: int, limit: int, tokens_used: int, token_ceiling: int) -> int:
    if limit <= 0:
        return 100
    ratios = [used * 100 // limit]
    if token_ceiling > 0:
        ratios.append(tokens_used * 100 // token_ceiling)
    return max(0, min(100, max(ratios)))


def seller_cap(limit: int, cap_percent: Optional[int]) -> Optional[int]:
    if cap_percent is None:
        return None
    return max(1, math.floor(limit * cap_percent / 100))


def usage_state(
    percent: int, warn_at: int, enforcement: str, blocked: bool
) -> Literal["shadow", "ok", "warning", "limit"]:
    if enforcement == "shadow":
        return "shadow"
    if blocked:
        return "limit"
    if percent >= warn_at:
        return "warning"
    return "ok"
