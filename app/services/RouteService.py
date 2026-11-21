"""Route-leg estimates through the Google Routes API, computeRoutes (POST /delivery/route-legs).

The legacy Directions API can't be enabled on new Google Cloud projects; Routes replaces it.
Costs money per request, so it ships off: with GOOGLE_DIRECTIONS_API_KEY unset (the key must
allow the Routes API) every call answers 503 {"code": "route_estimates_unavailable"} and the
client shows approximate distance only. Kept in the Essentials SKU: DRIVE, TRAFFIC_UNAWARE,
at most 10 intermediates (11 stops), no waypoint optimization, only leg distance and
duration in the field mask. Waypoints keep the rider's order. Results are cached 5 minutes
per origin + stops rounded to 4 decimals (~11 m). The key goes only in a request header to
Google and is never logged or returned.
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

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.legs.distanceMeters,routes.legs.duration"
KEY_ENV = "GOOGLE_DIRECTIONS_API_KEY"
# 10 intermediates + destination: more intermediates bill at a higher Routes SKU.
MAX_STOPS = 11
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


def _waypoint(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"location": {"latLng": {"latitude": float(p["lat"]), "longitude": float(p["lng"])}}}


def _seconds(duration: Any) -> float:
    """Routes durations are strings such as "165s"; zero values may be omitted."""
    if not duration:
        return 0.0
    return float(str(duration).rstrip("s"))


def _parse_legs(payload: Dict[str, Any], expected: int) -> List[Dict[str, Any]]:
    routes = payload.get("routes") or []
    if not routes:
        raise ValueError("no route")
    legs = (routes[0] or {}).get("legs") or []
    if len(legs) != expected:
        raise ValueError("leg count mismatch")
    out = []
    for leg in legs:
        meters = float(leg.get("distanceMeters") or 0)
        seconds = _seconds(leg.get("duration"))
        out.append({"km": round(meters / 1000, 1), "min": int(round(seconds / 60))})
    return out


def get_route_legs(
    origin: Dict[str, Any],
    stops: List[Dict[str, Any]],
    *,
    http_post: Callable[..., Any] = requests.post,
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

    body: Dict[str, Any] = {
        "origin": _waypoint(origin),
        "destination": _waypoint(stops[-1]),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
        "languageCode": "es-MX",
        "units": "METRIC",
    }
    if len(stops) > 1:
        body["intermediates"] = [_waypoint(s) for s in stops[:-1]]
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK}

    try:
        res = http_post(ROUTES_URL, json=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        if res.status_code != 200:
            # Only Google's status word: the error message can echo the key.
            status = ((res.json() or {}).get("error") or {}).get("status") if res.status_code < 500 else None
            logger.warning("routes unavailable: http=%s status=%s", res.status_code, status)
            raise RouteEstimatesUnavailable()
        legs = _parse_legs(res.json() or {}, len(stops))
    except RouteEstimatesUnavailable:
        raise
    except Exception as exc:
        # Exception text can carry request details (and the key): log the type only.
        logger.warning("routes request failed: %s", type(exc).__name__)
        raise RouteEstimatesUnavailable()

    _cache[cache_key] = (now + CACHE_TTL_SECONDS, legs)
    _cache.move_to_end(cache_key)
    while len(_cache) > CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)
    return [dict(leg) for leg in legs]
