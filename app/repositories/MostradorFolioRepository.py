from app.config import database
from bson import ObjectId
from pymongo import ReturnDocument
from typing import Any, Dict, List, Optional

COLLECTION = "MostradorFolios"


def _col():
    return database.db[COLLECTION]


def insert(folio: dict):
    return _col().insert_one(folio)


def find_by_id(id: str) -> Optional[dict]:
    try:
        return _col().find_one({"_id": ObjectId(id)})
    except Exception:
        return None


def find_by_folio_code(folio_code: str) -> Optional[dict]:
    return _col().find_one({"folio_code": folio_code})


def find_by_share_token(share_token: str) -> Optional[dict]:
    return _col().find_one({"share_token": share_token})


def find_by_tube_token(tube_token: str) -> Optional[dict]:
    return _col().find_one({"participant_shops.tube_token": tube_token})


def find(filters: Dict[str, Any]):
    return _col().find(filters).sort("updated_at", -1)


def find_orphans(group_id: str, limit: int = 20):
    """POS folios owned by the seller with no linked Eassymo buyer business."""
    filters = {
        "origin_group_id": group_id,
        "status": {"$ne": "canceled"},
        "$and": [
            {
                "$or": [
                    {"customer": None},
                    {"customer": {"$exists": False}},
                    {
                        "$and": [
                            {"$or": [
                                {"customer.group_id": None},
                                {"customer.group_id": {"$exists": False}},
                            ]},
                            {"$or": [
                                {"part_request_ids": {"$exists": False}},
                                {"part_request_ids": []},
                                {"part_request_ids": None},
                            ]},
                        ]
                    },
                ],
            },
        ],
    }
    return _col().find(filters).sort("updated_at", -1).limit(limit)


def edit(id: str, new_data: dict) -> Optional[dict]:
    return _col().find_one_and_update(
        {"_id": ObjectId(id)},
        {"$set": new_data},
        return_document=ReturnDocument.AFTER,
    )


def set_pieces(id: str, pieces: List[dict], updated_at) -> Optional[dict]:
    return _col().find_one_and_update(
        {"_id": ObjectId(id)},
        {"$set": {"pieces": pieces, "updated_at": updated_at}},
        return_document=ReturnDocument.AFTER,
    )


def set_piece_options(id: str, piece_id: str, options: List[dict], status: str, updated_at) -> Optional[dict]:
    """Targeted update of a single piece's options to avoid clobbering concurrent shops."""
    return _col().find_one_and_update(
        {"_id": ObjectId(id), "pieces.piece_id": piece_id},
        {"$set": {
            "pieces.$.options": options,
            "pieces.$.status": status,
            "updated_at": updated_at,
        }},
        return_document=ReturnDocument.AFTER,
    )


def set_piece_order(id: str, piece_id: str, order: Optional[dict], updated_at) -> Optional[dict]:
    return _col().find_one_and_update(
        {"_id": ObjectId(id), "pieces.piece_id": piece_id},
        {"$set": {
            "pieces.$.order": order,
            "updated_at": updated_at,
        }},
        return_document=ReturnDocument.AFTER,
    )


def push_participant_shop(id: str, shop: dict, visible_piece_ids: Optional[List[str]], updated_at) -> Optional[dict]:
    update: Dict[str, Any] = {
        "$push": {"participant_shops": shop},
        "$set": {"updated_at": updated_at},
    }
    return _col().find_one_and_update(
        {"_id": ObjectId(id)},
        update,
        return_document=ReturnDocument.AFTER,
    )
