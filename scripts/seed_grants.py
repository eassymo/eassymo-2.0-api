"""Seed the `grants` collection from scripts/data/grants_catalog.json.

Idempotent: only inserts missing keys, never overwrites edited text.
Usage: python -m scripts.seed_grants
"""
import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parent / "data" / "grants_catalog.json"


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def main(collection=None) -> int:
    from app.repositories import GrantRepository

    _coll = collection
    if _coll is None:
        from app.config import database
        _coll = database.db[GrantRepository.COLLECTION]
        _coll.create_index("key", unique=True)
    inserted = GrantRepository.upsert_missing(load_catalog(), collection=_coll)
    print(f"grants seeded: {inserted} inserted")
    return inserted


if __name__ == "__main__":
    main()
