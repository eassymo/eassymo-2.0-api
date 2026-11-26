"""Offers a store withdrew, kept whole with who and when (never hard-deleted). Restoring moves them back to Offers."""
from typing import Optional

from bson import ObjectId

from app.config import database


def _collection():
    return database.db["OffersArchive"]


def insert(doc: dict) -> None:
    _collection().insert_one(doc)


def find_by_id(offer_id: str) -> Optional[dict]:
    return _collection().find_one({"_id": ObjectId(offer_id)})


def delete(offer_id: str) -> None:
    _collection().delete_one({"_id": ObjectId(offer_id)})
