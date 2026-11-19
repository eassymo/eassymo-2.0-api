"""Policy for WhatsApp bot usage limits: reserve, settle, refund, snapshot, guard.

Modes (per call, from global settings and the store's tier):
- "off": global kill switch (`enforcement_enabled=False`); metered, never blocks.
- "shadow": `shadow_all` or tier `enforcement == "shadow"`; metered (even past
  the limit, so the data shows real demand), logs `would_block`, never blocks,
  no warning notices.
- "enforce": blocks with `UsageLimitReached`.

Every public method fails open: on any exception it logs
`whatsapp_usage_error`, bumps the settings error counter and lets the burst go.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from app.repositories import WhatsappInboundRepository as default_inbound_repo
from app.repositories import WhatsappUsageRepository as default_usage_repo
from app.services.whatsapp_usage_math import (
    effective_limit,
    percent_used,
    seller_cap,
    usage_state,
    window_end,
    window_expired,
)

logger = logging.getLogger(__name__)

BlockReason = Literal["quota", "tokens", "seller_cap"]
Mode = Literal["enforce", "shadow", "off"]

BURST_GUARD_SECONDS = 60
# Used to keep metering past the limit when not enforcing (fits in int64).
_UNLIMITED = 2**62


@dataclass
class UsageSnapshot:
    tier_id: str
    tier_name: str
    used: int
    limit: int
    tokens_used: int
    token_ceiling: int
    percent: int
    window_start: Optional[datetime]
    window_end: Optional[datetime]
    window_seconds: int
    state: Literal["shadow", "ok", "warning", "limit"]
    enforcement: Literal["shadow", "enforce"]


class UsageLimitReached(Exception):
    def __init__(self, reason: BlockReason, snapshot: UsageSnapshot):
        super().__init__(f"whatsapp usage limit reached: {reason}")
        self.reason = reason
        self.snapshot = snapshot


@dataclass
class UsageContext:
    group_id: str
    uid: str
    burst_id: str
    reserved: bool = False
    call_index: int = 0
    crossed_warning: bool = False
    snapshot: Optional[UsageSnapshot] = None


@dataclass
class _Policy:
    tier_id: str
    tier: Dict[str, Any]
    settings: Dict[str, Any]
    mode: Mode

    @property
    def display_enforcement(self) -> Literal["shadow", "enforce"]:
        # Kill switch: nothing is enforced, so sellers see it like shadow.
        return "enforce" if self.mode == "enforce" else "shadow"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class WhatsappUsageService:
    def __init__(self, repo: Any = None, inbound: Any = None):
        self.repo = repo or default_usage_repo
        self.inbound = inbound or default_inbound_repo

    # --- internals -----------------------------------------------------------

    def _fail_open(self, op: str, **fields: Any) -> None:
        logger.warning("whatsapp_usage_error op=%s %s", op, fields, exc_info=True)
        try:
            self.repo.incr_meter_errors()
        except Exception:
            logger.warning("whatsapp_usage_error op=incr_meter_errors", exc_info=True)

    def _policy(self, group_id: Optional[str]) -> _Policy:
        settings = self.repo.get_settings()
        normal_id = self.repo.NORMAL_TIER_ID
        tier_id = self.repo.get_store_tier_id(group_id) if group_id else normal_id
        tier = self.repo.get_tier(tier_id)
        if not tier or not tier.get("active", True):
            tier_id = normal_id
            tier = self.repo.get_tier(normal_id)
        if not tier:  # normal row not seeded yet
            tier = {**self.repo.NORMAL_TIER_SEED, "tier_id": normal_id}
        if not settings.get("enforcement_enabled", True):
            mode: Mode = "off"
        elif settings.get("shadow_all") or tier.get("enforcement", "shadow") != "enforce":
            mode = "shadow"
        else:
            mode = "enforce"
        return _Policy(tier_id=tier_id, tier=tier, settings=settings, mode=mode)

    def _build_snapshot(
        self,
        policy: _Policy,
        usage: Optional[dict],
        limit: int,
        now: datetime,
        uid: Optional[str] = None,
    ) -> UsageSnapshot:
        tier = policy.tier
        window_seconds = int(tier["window_seconds"])
        token_ceiling = int(tier["token_ceiling_per_window"])
        start = _aware((usage or {}).get("window_start"))
        if usage is None or window_expired(start, window_seconds, now):
            used, tokens, start, end, by_uid = 0, 0, None, None, {}
        else:
            used = int(usage.get("solicitudes_used", 0))
            tokens = int(usage.get("tokens_used", 0))
            end = window_end(start, window_seconds)
            by_uid = usage.get("by_uid") or {}
        percent = percent_used(used, limit, tokens, token_ceiling)
        blocked = used >= limit or tokens >= token_ceiling
        cap = seller_cap(limit, tier.get("per_seller_cap_percent"))
        if uid and cap is not None and int(by_uid.get(uid, 0)) >= cap:
            blocked = True
        return UsageSnapshot(
            tier_id=policy.tier_id,
            tier_name=str(tier.get("name") or policy.tier_id),
            used=used,
            limit=limit,
            tokens_used=tokens,
            token_ceiling=token_ceiling,
            percent=percent,
            window_start=start,
            window_end=end,
            window_seconds=window_seconds,
            state=usage_state(percent, int(tier.get("warn_at_percent", 80)), policy.display_enforcement, blocked),
            enforcement=policy.display_enforcement,
        )

    def _permissive_snapshot(self) -> UsageSnapshot:
        seed = self.repo.NORMAL_TIER_SEED
        return UsageSnapshot(
            tier_id=self.repo.NORMAL_TIER_ID,
            tier_name=str(seed["name"]),
            used=0,
            limit=int(seed["solicitudes_per_window"]),
            tokens_used=0,
            token_ceiling=int(seed["token_ceiling_per_window"]),
            percent=0,
            window_start=None,
            window_end=None,
            window_seconds=int(seed["window_seconds"]),
            state="shadow",
            enforcement="shadow",
        )

    def _log_decision(self, ctx: UsageContext, decision: str, reason: str, mode: Mode) -> None:
        logger.info(
            "whatsapp_usage decision=%s reason=%s mode=%s group_id=%s uid=%s burst_id=%s",
            decision, reason, mode, ctx.group_id, ctx.uid, ctx.burst_id,
        )

    # --- public API ------------------------------------------------------------

    def snapshot(self, group_id: str, uid: Optional[str] = None, now: Optional[datetime] = None) -> UsageSnapshot:
        """Current store usage. An expired or missing window reads as fresh;
        with `uid`, a seller at the per-seller cap reads as `limit`."""
        now = now or _now()
        try:
            policy = self._policy(group_id)
            usage = self.repo.get_usage(group_id)
            start = _aware((usage or {}).get("window_start"))
            active = usage is not None and not window_expired(start, int(policy.tier["window_seconds"]), now)
            grants = self.repo.sum_grants(group_id, start if active else None)
            limit = effective_limit(int(policy.tier["solicitudes_per_window"]), grants)
            return self._build_snapshot(policy, usage, limit, now, uid=uid)
        except Exception:
            self._fail_open("snapshot", group_id=group_id)
            return self._permissive_snapshot()

    def reserve(self, ctx: UsageContext, now: Optional[datetime] = None) -> None:
        """Charge one solicitud for the burst (idempotent per `burst_id`).
        Raises `UsageLimitReached` only in enforce mode."""
        if ctx.reserved:
            return
        now = now or _now()
        try:
            policy = self._policy(ctx.group_id)
            tier = policy.tier
            doc = self.repo.ensure_window(ctx.group_id, policy.tier_id, int(tier["window_seconds"]), now)
            window_start = doc["window_start"]
            self.repo.bind_pending_grants(ctx.group_id, window_start)
            limit = effective_limit(
                int(tier["solicitudes_per_window"]), self.repo.sum_grants(ctx.group_id, window_start)
            )
            ceiling = int(tier["token_ceiling_per_window"])
            cap = seller_cap(limit, tier.get("per_seller_cap_percent"))
            result = self.repo.try_reserve(
                ctx.group_id, ctx.uid, ctx.burst_id,
                limit=limit, token_ceiling=ceiling, seller_cap=cap, window_start=window_start,
            )

            if result.startswith("blocked_"):
                reason: BlockReason = result[len("blocked_"):]  # type: ignore[assignment]
                if policy.mode == "enforce":
                    usage = self.repo.get_usage(ctx.group_id) or doc
                    snap = self._build_snapshot(policy, usage, limit, now, uid=ctx.uid)
                    snap.state = "limit"  # the re-read can race a refund; the block stands
                    ctx.snapshot = snap
                    self._log_decision(ctx, "blocked", reason, policy.mode)
                    raise UsageLimitReached(reason, snap)
                self._log_decision(ctx, "would_block", reason, policy.mode)
                # Not enforcing: keep metering past the limit.
                result = self.repo.try_reserve(
                    ctx.group_id, ctx.uid, ctx.burst_id,
                    limit=_UNLIMITED, token_ceiling=_UNLIMITED, seller_cap=None,
                    window_start=window_start,
                )

            ctx.reserved = True
            # try_reserve may have landed in a newer window: re-read and use it.
            fresh = self.repo.get_usage(ctx.group_id) or doc
            if fresh.get("window_start") != window_start:
                limit = effective_limit(
                    int(tier["solicitudes_per_window"]), self.repo.sum_grants(ctx.group_id, fresh["window_start"])
                )
            snap = self._build_snapshot(policy, fresh, limit, now)
            ctx.snapshot = snap
            if (
                result == "reserved"
                and policy.mode == "enforce"
                and snap.percent >= int(tier.get("warn_at_percent", 80))
                and self.repo.claim_warning(ctx.group_id, fresh["window_start"])
            ):
                ctx.crossed_warning = True
            self._log_decision(ctx, result, "", policy.mode)
        except UsageLimitReached:
            raise
        except Exception:
            self._fail_open("reserve", group_id=ctx.group_id, burst_id=ctx.burst_id)

    def ensure_tokens_available(self, ctx: UsageContext, now: Optional[datetime] = None) -> None:
        """Follow-up bursts: never use a solicitud, but obey the token ceiling."""
        now = now or _now()
        try:
            policy = self._policy(ctx.group_id)
            usage = self.repo.get_usage(ctx.group_id)
            start = _aware((usage or {}).get("window_start"))
            if usage is None or window_expired(start, int(policy.tier["window_seconds"]), now):
                return
            if int(usage.get("tokens_used", 0)) < int(policy.tier["token_ceiling_per_window"]):
                return
            if policy.mode != "enforce":
                self._log_decision(ctx, "would_block", "tokens", policy.mode)
                return
            limit = effective_limit(
                int(policy.tier["solicitudes_per_window"]), self.repo.sum_grants(ctx.group_id, start)
            )
            snap = self._build_snapshot(policy, usage, limit, now)
            ctx.snapshot = snap
            self._log_decision(ctx, "blocked", "tokens", policy.mode)
            raise UsageLimitReached("tokens", snap)
        except UsageLimitReached:
            raise
        except Exception:
            self._fail_open("ensure_tokens_available", group_id=ctx.group_id, burst_id=ctx.burst_id)

    def record_call(
        self,
        ctx: UsageContext,
        kind: str,
        usage: Optional[dict],
        *,
        counted: bool,
        status: str = "ok",
        model: str = "",
    ) -> None:
        """Ledger event for one GLM call (`event_id = burst_id:call_index`) and
        add its tokens to the counters. Missing usage records zero tokens."""
        call_index = ctx.call_index
        ctx.call_index += 1
        try:
            usage_missing = usage is None or usage.get("has_usage") is False
            data = usage or {}
            prompt = int(data.get("prompt_tokens") or 0)
            completion = int(data.get("completion_tokens") or 0)
            policy = self._policy(ctx.group_id)
            settings = policy.settings
            cost = (
                prompt / 1000 * float(settings.get("price_per_1k_prompt_tokens") or 0)
                + completion / 1000 * float(settings.get("price_per_1k_completion_tokens") or 0)
            )
            inserted = self.repo.insert_event(
                {
                    "event_id": f"{ctx.burst_id}:{call_index}",
                    "group_id": ctx.group_id,
                    "uid": ctx.uid,
                    "burst_id": ctx.burst_id,
                    "tier_id": policy.tier_id,
                    "kind": kind,
                    "counted": bool(counted),
                    "status": status,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "model": model or str(data.get("model") or ""),
                    "estimated_cost": round(cost, 6),
                    "enforcement_mode": policy.mode,
                    "usage_missing": usage_missing,
                    "created_at": _now(),
                }
            )
            if inserted:  # a duplicate event (retry) must not add tokens twice
                self.repo.add_tokens(ctx.group_id, prompt + completion)
        except Exception:
            self._fail_open("record_call", group_id=ctx.group_id, burst_id=ctx.burst_id)

    def refund(self, ctx: UsageContext) -> None:
        """Release this burst's solicitud (GLM failed). No-op unless reserved."""
        if not ctx.reserved:
            return
        try:
            self.repo.refund(ctx.group_id, ctx.uid, ctx.burst_id)
            ctx.reserved = False
        except Exception:
            self._fail_open("refund", group_id=ctx.group_id, burst_id=ctx.burst_id)

    def check_burst_guard(self, group_id: str, phone: str, now: Optional[datetime] = None) -> bool:
        """True = allowed. More than `burst_messages_per_minute` inbound
        messages from this phone in 60 s is blocked (only when enforcing)."""
        try:
            policy = self._policy(group_id)
            per_minute = int(policy.tier.get("burst_messages_per_minute") or 0)
            if per_minute <= 0:
                return True
            count = self.inbound.count_recent(phone, BURST_GUARD_SECONDS, now)
            if count <= per_minute:
                return True
            decision = "guard_blocked" if policy.mode == "enforce" else "guard_would_block"
            logger.info(
                "whatsapp_usage decision=%s reason=burst mode=%s group_id=%s count=%s limit=%s",
                decision, policy.mode, group_id, count, per_minute,
            )
            return policy.mode != "enforce"
        except Exception:
            self._fail_open("check_burst_guard", group_id=group_id)
            return True
