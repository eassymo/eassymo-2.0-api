"""Seed the `frames` collection from scripts/data/frames_catalog.json (approved frames-catalog.csv).

Idempotent: only inserts missing codes, never overwrites edited text or screenshots.
Usage: python -m scripts.seed_frames
"""
import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parent / "data" / "frames_catalog.json"


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def main(collection=None) -> int:
    from app.repositories import FrameRepository

    coll = collection
    if coll is None:
        from app.config import database
        coll = database.db[FrameRepository.COLLECTION]
        coll.create_index("code", unique=True)
    inserted = FrameRepository.upsert_missing(load_catalog(), collection=coll)
    print(f"frames seeded: {inserted} inserted")
    return inserted


if __name__ == "__main__":
    main()
