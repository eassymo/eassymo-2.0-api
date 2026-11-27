"""Offers a store withdrew, kept whole with who and when (never hard-deleted). Restoring moves them back to Offers."""
from typing import List, Optional

from bson import ObjectId

from app.config import database


def _collection():
    return database.db["OffersArchive"]


def insert(doc: dict) -> None:
    _collection().insert_one(doc)


def upsert(doc: dict) -> None:
    """Archive the offer, replacing an earlier copy of it (a retried removal archives the same offer again)."""
    _collection().replace_one({"_id": doc["_id"]}, doc, upsert=True)


def find(filters: dict) -> List[dict]:
    return list(_collection().find(filters))


def find_by_id(offer_id: str) -> Optional[dict]:
    return _collection().find_one({"_id": ObjectId(offer_id)})


def delete(offer_id: str) -> None:
    _collection().delete_one({"_id": ObjectId(offer_id)})
