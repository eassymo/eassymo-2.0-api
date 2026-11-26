"""Who received an order: every part's sellers and followers, one entry per store."""
import math
from collections import Counter
from typing import List, Optional, Set

from app.repositories import GroupRepository as groupRepository
from app.schemas.PartRequest import PartRequest


def part_stores(doc: PartRequest) -> Set[str]:
    """Stores a part went to. The reach endpoint's audience_total is the size of their union."""
    return {i for i in [*(doc.subscribedSellers or []), *(doc.subscribedFollowers or [])] if i}


def _location(group: Optional[dict]) -> Optional[dict]:
    """
    GeoJSON point ([lng, lat]) to {lat, lng}. None for anything else: no location, a location that isn't a dict, fewer
    than two coordinates, a coordinate that isn't a number (numeric strings are read), or the [0, 0] placeholder.
    Never raises, so one bad group record can't fail the whole list.
    """
    location = group.get("location") if isinstance(group, dict) else None
    coords = location.get("coordinates") if isinstance(location, dict) else None
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    try:
        lng, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lng) and math.isfinite(lat)) or (lng == 0 and lat == 0):
        return None
    return {"lat": lat, "lng": lng}


def recipients(parts: List[PartRequest]) -> dict:
    counts = Counter(g for p in parts for g in part_stores(p))
    groups = {
        str(g["_id"]): g
        for g in groupRepository.find_many_by_string_ids(list(counts), {"name": 1, "location": 1})
    }
    rows = [
        {
            "group_id": gid,
            "name": (groups.get(gid) or {}).get("name"),
            "location": _location(groups.get(gid)),
            "parts": n,
        }
        for gid, n in counts.items()
    ]
    rows.sort(key=lambda r: (-r["parts"], (r["name"] or "").lower()))
    non_compatible = {s.group_id for p in parts for s in (p.nonCompatibleSellers or []) if s.group_id}
    vehicle = parts[0].vehicleInformation if parts else None
    return {
        "recipients": rows,
        "non_compatible": len(non_compatible),
        "maker": vehicle.maker if vehicle else None,
    }
