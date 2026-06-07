from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError
from zoneinfo import ZoneInfo

from app.config import database

db = database.db["group_configs"]

try:
    db.create_index("group_id", unique=True)
except PyMongoError:
    pass


def find_by_group_ids(group_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not group_ids:
        return {}
    try:
        unique_ids = list({gid.strip() for gid in group_ids if gid and gid.strip()})
        if not unique_ids:
            return {}
        result: Dict[str, Dict[str, Any]] = {}
        for doc in db.find({"group_id": {"$in": unique_ids}}):
            if isinstance(doc.get("_id"), ObjectId):
                doc["_id"] = str(doc["_id"])
            group_id = doc.get("group_id")
            if group_id:
                result[str(group_id)] = doc
        return result
    except PyMongoError as e:
        raise PyMongoError(
            f"Error finding group configs for group_ids={group_ids}: {str(e)}"
        )


def find_by_group_id(group_id: str) -> Optional[Dict[str, Any]]:
    try:
        doc = db.find_one({"group_id": group_id})
        if doc is None:
            return None
        if isinstance(doc.get("_id"), ObjectId):
            doc["_id"] = str(doc["_id"])
        return doc
    except PyMongoError as e:
        raise PyMongoError(f"Error finding group config for group_id={group_id}: {str(e)}")


def upsert_armadoras(
    group_id: str, armadoras: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        now = datetime.now(ZoneInfo("UTC"))
        updated_doc = db.find_one_and_update(
            {"group_id": group_id},
            {
                "$set": {
                    "armadoras": armadoras,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "group_id": group_id,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if isinstance(updated_doc.get("_id"), ObjectId):
            updated_doc["_id"] = str(updated_doc["_id"])
        return updated_doc
    except PyMongoError as e:
        raise PyMongoError(
            f"Error upserting armadoras config for group_id={group_id}: {str(e)}"
        )
