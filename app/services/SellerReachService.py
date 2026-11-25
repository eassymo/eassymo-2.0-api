"""Seller reach cap: limits, local day and the typed 409 error."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from app.repositories import SellerReachRepository as repo

TZ = ZoneInfo("America/Mexico_City")


@dataclass(frozen=True)
class Limits:
    wide_threshold: int
    wide_per_day: int
    capped_max: int
    enforce: bool


class SellerReachError(HTTPException):
    def __init__(self, code: Literal["seller_cap_exceeded", "request_full"], message: str, data: dict):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=message)
        self.code = code
        self.message = message
        self.data = data


def limits_for(group_id: str) -> Limits:
    merged = dict(repo.get_settings())
    override = repo.get_override(group_id) or {}
    for key in ("wide_threshold", "wide_per_day", "capped_max", "enforcement"):
        if override.get(key) is not None:
            merged[key] = override[key]
    return Limits(
        wide_threshold=int(merged["wide_threshold"]),
        wide_per_day=int(merged["wide_per_day"]),
        capped_max=int(merged["capped_max"]),
        enforce=merged["enforcement"] == "enforce",
    )


def _local(now: datetime) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(TZ)


def local_day(now: datetime) -> str:
    return _local(now).strftime("%Y-%m-%d")


def renews_at(now: datetime) -> datetime:
    next_day = _local(now).date() + timedelta(days=1)
    return datetime.combine(next_day, time.min, tzinfo=TZ).astimezone(timezone.utc)


def audience(subscribed: List[str], followers: Optional[List[str]]) -> int:
    return len({i for i in [*(subscribed or []), *(followers or [])] if i})


def today(group_id: str, now: datetime) -> dict:
    limits = limits_for(group_id)
    day = local_day(now)
    used = int(repo.get_usage(group_id, day).get("wide_used", 0))
    return {
        "day": day,
        "wide_used": used,
        "wide_per_day": limits.wide_per_day,
        "wide_left": max(limits.wide_per_day - used, 0),
        "wide_threshold": limits.wide_threshold,
        "capped_max": limits.capped_max,
        "renews_at": renews_at(now).isoformat(),
        "enforcement": "enforce" if limits.enforce else "shadow",
    }


def release(group_id: str, day: str, request_id: str) -> None:
    """Give back a slot this request reserved (a create that failed after deciding)."""
    repo.release_wide(group_id, day, request_id)
    repo.write_event("wide_released", group_id, request_id=request_id, day=day)


def preview(payload, now: datetime) -> dict:
    """Each part's audience as create would resolve it, against today's limits. Reserves and writes nothing."""
    from app.services import PartRequestService  # PartRequestService imports this module

    info = today(payload.group_id, now)
    parts = PartRequestService.compute_part_audiences(
        payload.group_id,
        payload.vehicle_id,
        payload.part_list,
        payload.subscribed_sellers,
        payload.subscribed_followers,
        payload.commissioner_group,
    )
    return {
        "today": info,
        "parts": [
            {"index": p["index"], "audience": p["audience"], "needs_wide": p["audience"] >= info["wide_threshold"]}
            for p in parts
        ],
    }


CAP_MESSAGE = (
    "Hoy ya usaste tus {wide_per_day} envíos a {wide_threshold} tiendas o más. "
    "Esta pieza puede llegar a {capped_max} tiendas como máximo."
)


def decide(
    group_id: str,
    request_id: str,
    new_audience: int,
    previous_audience: int,
    current_tier: Optional[str],
    now: datetime,
) -> dict:
    """Pick the reach tier for one PartRequest at `new_audience`, reserving a wide slot when needed.

    Slots count against today's local day (never the doc's creation day). Events: `wide_reserved` on a
    fresh reservation; `capped` when a new doc or a growth ends capped; `would_block` (shadow) or
    `refused` (enforce) when a new doc or a growth goes past `capped_max` with no slot left.
    """
    limits = limits_for(group_id)
    day = local_day(now)

    def result(tier: str) -> dict:
        return {"tier": tier, "day": day, "audience": new_audience}

    def event(kind: str) -> None:
        repo.write_event(kind, group_id, request_id=request_id, day=day, audience=new_audience,
                         previous_audience=previous_audience)

    # 1. Already wide: never limited.
    if current_tier == "wide":
        return result("wide")

    # 2. Wide audience: take a slot.
    if new_audience >= limits.wide_threshold:
        reserved = repo.try_reserve_wide(group_id, day, request_id, limits.wide_per_day)
        if reserved != "exhausted":
            if reserved == "reserved":
                event("wide_reserved")
            return result("wide")
    # 3. Below the threshold with slots left.
    elif int(repo.get_usage(group_id, day).get("wide_used", 0)) < limits.wide_per_day:
        return result("normal")

    # No slot left today.
    grows = new_audience > previous_audience or (previous_audience == 0 and current_tier is None)
    if new_audience <= limits.capped_max or not grows:
        if grows:
            event("capped")
        return result("capped")

    # 4. A new doc or a growth past capped_max.
    if not limits.enforce:
        event("would_block")
        event("capped")
        return result("capped")

    event("refused")
    raise SellerReachError(
        "seller_cap_exceeded",
        CAP_MESSAGE.format(
            wide_per_day=limits.wide_per_day, wide_threshold=limits.wide_threshold, capped_max=limits.capped_max
        ),
        {
            "request_id": request_id,
            "audience": new_audience,
            "max_allowed": limits.capped_max,
            "wide_left": 0,
            "renews_at": renews_at(now).isoformat(),
        },
    )


def room(doc, now: datetime) -> Optional[int]:
    """How many more stores a part can take today. `None` = no limit. Pure read: reserves and writes nothing.

    A wide doc (or a legacy one without `reach` already at the wide threshold) is never limited, and
    neither is one while wide slots remain today; otherwise it can grow up to `capped_max`.
    """
    limits = limits_for(doc.creatorGroup)
    current = audience(doc.subscribedSellers, doc.subscribedFollowers)
    tier = (doc.reach or {}).get("tier")
    if tier == "wide" or (doc.reach is None and current >= limits.wide_threshold):
        return None
    if int(repo.get_usage(doc.creatorGroup, local_day(now)).get("wide_used", 0)) < limits.wide_per_day:
        return None
    return max(limits.capped_max - current, 0)
