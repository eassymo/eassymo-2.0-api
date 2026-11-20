"""Route-leg estimates through Google Directions (POST /delivery/route-legs).

Costs money per request, so it ships off: with GOOGLE_DIRECTIONS_API_KEY unset every call
answers 503 {"code": "route_estimates_unavailable"} and the client shows approximate
distance only. Waypoints keep the rider's order (never optimized). Results are cached
5 minutes per origin + stops rounded to 4 decimals (~11 m). The key is sent only to
Google and never logged or returned.
"""
from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Tuple

import requests
from fastapi import HTTPException

logger = logging.getLogger(__name__)

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
KEY_ENV = "GOOGLE_DIRECTIONS_API_KEY"
MAX_STOPS = 12
CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 1000
REQUEST_TIMEOUT_SECONDS = 8

_cache: "OrderedDict[Tuple, Tuple[float, List[Dict[str, Any]]]]" = OrderedDict()


class RouteEstimatesUnavailable(HTTPException):
    code = "route_estimates_unavailable"

    def __init__(self):
        super().__init__(status_code=503, detail="Route estimates are unavailable")


def _now() -> float:
    return time.monotonic()


def clear_cache() -> None:
    _cache.clear()


def _point(p: Dict[str, Any]) -> Tuple[float, float]:
    return round(float(p["lat"]), 4), round(float(p["lng"]), 4)


def _fmt(p: Dict[str, Any]) -> str:
    return f"{float(p['lat'])},{float(p['lng'])}"


def _parse_legs(payload: Dict[str, Any], expected: int) -> List[Dict[str, Any]]:
    legs = ((payload.get("routes") or [{}])[0] or {}).get("legs") or []
    if len(legs) != expected:
        raise ValueError("leg count mismatch")
    out = []
    for leg in legs:
        meters = leg["distance"]["value"]
        seconds = leg["duration"]["value"]
        out.append({"km": round(meters / 1000, 1), "min": int(round(seconds / 60))})
    return out


def get_route_legs(
    origin: Dict[str, Any],
    stops: List[Dict[str, Any]],
    *,
    http_get: Callable[..., Any] = requests.get,
) -> List[Dict[str, Any]]:
    """One {km, min} per stop, in the order given (origin -> stop 1 -> stop 2 ...)."""
    if len(stops) > MAX_STOPS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_STOPS} stops")
    if not stops:
        return []

    key = (os.getenv(KEY_ENV) or "").strip()
    if not key:
        raise RouteEstimatesUnavailable()

    cache_key = (_point(origin), tuple(_point(s) for s in stops))
    now = _now()
    hit = _cache.get(cache_key)
    if hit and hit[0] > now:
        return [dict(leg) for leg in hit[1]]

    params = {
        "origin": _fmt(origin),
        "destination": _fmt(stops[-1]),
        "mode": "driving",
        "language": "es",
        "key": key,
    }
    if len(stops) > 1:
        params["waypoints"] = "|".join(_fmt(s) for s in stops[:-1])

    try:
        res = http_get(DIRECTIONS_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        payload = res.json() if res.status_code == 200 else {}
        status = payload.get("status")
        if status != "OK":
            # Only Google's status word: error_message can echo the key.
            logger.warning("directions unavailable: http=%s status=%s", res.status_code, status)
            raise RouteEstimatesUnavailable()
        legs = _parse_legs(payload, len(stops))
    except RouteEstimatesUnavailable:
        raise
    except Exception as exc:
        # Exception text can carry the request URL (and the key): log the type only.
        logger.warning("directions request failed: %s", type(exc).__name__)
        raise RouteEstimatesUnavailable()

    _cache[cache_key] = (now + CACHE_TTL_SECONDS, legs)
    _cache.move_to_end(cache_key)
    while len(_cache) > CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)
    return [dict(leg) for leg in legs]
