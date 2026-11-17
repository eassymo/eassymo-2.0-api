from datetime import datetime, timezone
from typing import Any, Dict, List

from app.config import database

COLLECTION = "frames"


def _coll(collection=None):
    return collection if collection is not None else database.db[COLLECTION]


def upsert_missing(docs: List[Dict[str, Any]], collection=None) -> int:
    """Insert catalog frames whose code is not stored yet; never touches existing docs.
    Grant links are not stored on frames (they live on grants as `frame_refs`)."""
    coll = _coll(collection)
    codes = [d["code"] for d in docs]
    existing = {d["code"] for d in coll.find({"code": {"$in": codes}}, {"code": 1})}
    now = datetime.now(timezone.utc)
    missing = [
        {**{k: v for k, v in d.items() if k != "grants"}, "created_at": now, "updated_at": now}
        for d in docs if d["code"] not in existing
    ]
    if missing:
        coll.insert_many(missing)
    return len(missing)
