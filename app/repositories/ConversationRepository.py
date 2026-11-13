"""Read-only queries behind the messages inbox."""
from typing import Dict, Iterable, List

from bson import ObjectId

from app.config import database

_REQUEST_PROJECTION = {
    "creatorGroup": 1,
    "subscribedSellers": 1,
    "subscribedFollowers": 1,
    "status": 1,
    "isActive": 1,
    "createdAt": 1,
    "part.tipoParteDescripcion": 1,
    "vehicleInformation.maker": 1,
    "vehicleInformation.model": 1,
    "vehicleInformation.year": 1,
}

_ORDER_PROJECTION = {
    "order_id": 1,
    "group": 1,
    "offer.group_id": 1,
    "status": 1,
    "offer_group._id": 1,
    "offer_group.name": 1,
    "request_group._id": 1,
    "request_group.name": 1,
}


def request_docs_for_group(group_id: str) -> List[dict]:
    gid = str(group_id)
    return list(
        database.db["PartRequests"].find(
            {"$or": [
                {"creatorGroup": gid},
                {"subscribedSellers": gid},
                {"subscribedFollowers": gid},
            ]},
            _REQUEST_PROJECTION,
        )
    )


def order_docs_for_group(group_id: str) -> List[dict]:
    gid = str(group_id)
    return list(
        database.db["Orders"].find(
            {"$or": [{"group": gid}, {"offer.group_id": gid}]},
            _ORDER_PROJECTION,
        )
    )


def chats_for(request_ids: Iterable[str], order_ids: Iterable[str]) -> List[dict]:
    rids = [str(r) for r in request_ids]
    oids = [str(o) for o in order_ids]
    if not rids and not oids:
        return []
    return list(
        database.db["Chats"].find(
            {"$or": [{"requestId": {"$in": rids}}, {"orderId": {"$in": oids}}]},
            {"requestId": 1, "orderId": 1, "messages": 1},
        )
    )


def group_names(ids: Iterable[str]) -> Dict[str, str]:
    oids = []
    for value in ids:
        try:
            oids.append(ObjectId(str(value)))
        except Exception:
            continue
    if not oids:
        return {}
    return {
        str(doc["_id"]): doc.get("name") or ""
        for doc in database.db["groups"].find({"_id": {"$in": oids}}, {"name": 1})
    }
