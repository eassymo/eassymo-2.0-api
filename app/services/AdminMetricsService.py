from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.config import database

db = database.db


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _date_match(field: str, date_from: Optional[str], date_to: Optional[str]) -> Dict[str, Any]:
    match: Dict[str, Any] = {}
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    if start or end:
        range_filter: Dict[str, Any] = {}
        if start:
            range_filter["$gte"] = start
        if end:
            range_filter["$lte"] = end
        match[field] = range_filter
    return match


def _group_filter(group_id: Optional[str]) -> Dict[str, Any]:
    if not group_id:
        return {}
    return {"group_id": group_id}


def _part_request_group_filter(group_id: Optional[str]) -> Dict[str, Any]:
    if not group_id:
        return {}
    return {"creatorGroup": group_id}


def _order_group_filter(group_id: Optional[str]) -> Dict[str, Any]:
    if not group_id:
        return {}
    return {"group": group_id}


def _granularity_format(granularity: str) -> str:
    if granularity == "week":
        return "%Y-W%V"
    if granularity == "month":
        return "%Y-%m"
    return "%Y-%m-%d"


def _coerce_date_add_fields(date_field: str, alias: str = "_normalizedDate") -> Dict[str, Any]:
    """Normalize BSON Date or ISO string date fields for aggregations."""
    return {
        "$addFields": {
            alias: {
                "$cond": {
                    "if": {"$eq": [{"$type": f"${date_field}"}, "string"]},
                    "then": {
                        "$dateFromString": {
                            "dateString": f"${date_field}",
                            "onError": None,
                            "onNull": None,
                        }
                    },
                    "else": f"${date_field}",
                }
            }
        }
    }


def _date_to_string_group_id(date_alias: str, granularity: str) -> Dict[str, Any]:
    return {
        "$dateToString": {
            "format": _granularity_format(granularity),
            "date": f"${date_alias}",
        }
    }


def _serialize_value(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value


def _serialize_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if doc is None:
        return None
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return _serialize_value(out)


def _serialize_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_serialize_doc(d) for d in docs]


def _count_by_field(collection: str, field: str, base_match: Dict[str, Any]) -> List[Dict[str, Any]]:
    pipeline = [
        {"$match": base_match},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    rows = list(db[collection].aggregate(pipeline))
    return [{"key": row["_id"], "count": row["count"]} for row in rows]


def _time_series(
    collection: str,
    date_field: str,
    base_match: Dict[str, Any],
    granularity: str,
) -> List[Dict[str, Any]]:
    date_alias = "_normalizedDate"
    pipeline = [
        {"$match": base_match},
        _coerce_date_add_fields(date_field, date_alias),
        {"$match": {date_alias: {"$exists": True, "$ne": None}}},
        {
            "$group": {
                "_id": _date_to_string_group_id(date_alias, granularity),
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    rows = list(db[collection].aggregate(pipeline))
    return [{"period": row["_id"], "count": row["count"]} for row in rows if row.get("_id")]


def _paginate(
    collection: str,
    match: Dict[str, Any],
    page: int,
    page_size: int,
    sort_field: str = "createdAt",
) -> Dict[str, Any]:
    skip = max(page - 1, 0) * page_size
    total = db[collection].count_documents(match)
    cursor = (
        db[collection]
        .find(match)
        .sort(sort_field, -1)
        .skip(skip)
        .limit(page_size)
    )
    return {
        "items": _serialize_docs(list(cursor)),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 1),
    }


class AdminMetricsService:
    @staticmethod
    def get_overview(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        pr_match = {
            **_date_match("createdAt", date_from, date_to),
            **_part_request_group_filter(group_id),
        }
        offer_match = {
            **_date_match("createdAt", date_from, date_to),
            **_group_filter(group_id),
        }
        order_match = {
            **_date_match("created_at", date_from, date_to),
            **_order_group_filter(group_id),
        }

        part_requests = db["PartRequests"].count_documents(pr_match)
        offers = db["Offers"].count_documents(offer_match)
        orders = db["Orders"].count_documents(order_match)
        users = db["Users"].count_documents({})
        groups = db["groups"].count_documents({})

        selected_offers = db["Offers"].count_documents({**offer_match, "status": "Selected"})
        received_orders = db["Orders"].count_documents({**order_match, "status": "RECIEVED"})
        canceled_orders = db["Orders"].count_documents({**order_match, "status": "CANCELED"})

        gmv_pipeline = [
            {"$match": order_match},
            {
                "$group": {
                    "_id": None,
                    "gmv": {"$sum": {"$ifNull": ["$offer.price", 0]}},
                    "avg_order_value": {"$avg": {"$ifNull": ["$offer.price", 0]}},
                }
            },
        ]
        gmv_result = list(db["Orders"].aggregate(gmv_pipeline))
        gmv = gmv_result[0]["gmv"] if gmv_result else 0
        aov = gmv_result[0]["avg_order_value"] if gmv_result else 0

        return {
            "totals": {
                "part_requests": part_requests,
                "offers": offers,
                "orders": orders,
                "users": users,
                "groups": groups,
            },
            "funnel": {
                "part_requests": part_requests,
                "offers": offers,
                "selected_offers": selected_offers,
                "orders": orders,
                "received_orders": received_orders,
                "canceled_orders": canceled_orders,
            },
            "gmv": round(gmv or 0, 2),
            "avg_order_value": round(aov or 0, 2),
            "conversion_rates": {
                "request_to_offer": round((offers / part_requests * 100) if part_requests else 0, 2),
                "offer_to_selected": round((selected_offers / offers * 100) if offers else 0, 2),
                "order_to_received": round((received_orders / orders * 100) if orders else 0, 2),
            },
        }

    @staticmethod
    def get_part_requests_metrics(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        group_id: Optional[str] = None,
        granularity: str = "day",
    ) -> Dict[str, Any]:
        base_match = {
            **_date_match("createdAt", date_from, date_to),
            **_part_request_group_filter(group_id),
        }
        total = db["PartRequests"].count_documents(base_match)
        with_offers = db["PartRequests"].count_documents({**base_match, "offers_amount": {"$gt": 0}})
        selected = db["PartRequests"].count_documents({**base_match, "status": "Offer_selected"})

        avg_offers_pipeline = [
            {"$match": base_match},
            {"$group": {"_id": None, "avg": {"$avg": {"$ifNull": ["$offers_amount", 0]}}}},
        ]
        avg_offers = list(db["PartRequests"].aggregate(avg_offers_pipeline))
        avg_offers_value = avg_offers[0]["avg"] if avg_offers else 0

        top_groups_pipeline = [
            {"$match": base_match},
            {"$group": {"_id": "$creatorGroup", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top_groups = [
            {"group_id": row["_id"], "count": row["count"]}
            for row in db["PartRequests"].aggregate(top_groups_pipeline)
        ]

        return {
            "total": total,
            "by_status": _count_by_field("PartRequests", "status", base_match),
            "by_fulfillment_type": _count_by_field("PartRequests", "fulfillment_type", base_match),
            "active_vs_inactive": [
                {"key": True, "count": db["PartRequests"].count_documents({**base_match, "isActive": True})},
                {"key": False, "count": db["PartRequests"].count_documents({**base_match, "isActive": False})},
            ],
            "created_over_time": _time_series("PartRequests", "createdAt", base_match, granularity),
            "avg_offers_per_request": round(avg_offers_value or 0, 2),
            "fill_rate_percent": round((with_offers / total * 100) if total else 0, 2),
            "selection_rate_percent": round((selected / total * 100) if total else 0, 2),
            "top_creator_groups": top_groups,
        }

    @staticmethod
    def get_offers_metrics(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        group_id: Optional[str] = None,
        granularity: str = "day",
    ) -> Dict[str, Any]:
        base_match = {
            **_date_match("createdAt", date_from, date_to),
            **_group_filter(group_id),
        }
        total = db["Offers"].count_documents(base_match)
        selected = db["Offers"].count_documents({**base_match, "status": "Selected"})
        call_center = db["Offers"].count_documents({
            **base_match,
            "call_center_that_posted_offer": {"$exists": True, "$ne": None},
        })
        commissioner = db["Offers"].count_documents({
            **base_match,
            "commissioner_price": {"$exists": True, "$ne": None},
        })

        price_pipeline = [
            {"$match": {**base_match, "price": {"$exists": True, "$ne": None}}},
            {
                "$group": {
                    "_id": None,
                    "avg": {"$avg": "$price"},
                    "min": {"$min": "$price"},
                    "max": {"$max": "$price"},
                }
            },
        ]
        price_stats = list(db["Offers"].aggregate(price_pipeline))
        prices = price_stats[0] if price_stats else {"avg": 0, "min": 0, "max": 0}

        top_sellers_pipeline = [
            {"$match": base_match},
            {"$group": {"_id": "$group_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top_sellers = [
            {"group_id": row["_id"], "count": row["count"]}
            for row in db["Offers"].aggregate(top_sellers_pipeline)
        ]

        return {
            "total": total,
            "by_status": _count_by_field("Offers", "status", base_match),
            "created_over_time": _time_series("Offers", "createdAt", base_match, granularity),
            "selection_rate_percent": round((selected / total * 100) if total else 0, 2),
            "price_stats": {
                "avg": round(prices.get("avg") or 0, 2),
                "min": round(prices.get("min") or 0, 2),
                "max": round(prices.get("max") or 0, 2),
            },
            "call_center_posted": call_center,
            "commissioner_offers": commissioner,
            "top_seller_groups": top_sellers,
        }

    @staticmethod
    def get_orders_metrics(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        group_id: Optional[str] = None,
        granularity: str = "day",
    ) -> Dict[str, Any]:
        base_match = {
            **_date_match("createdAt", date_from, date_to),
            **_order_group_filter(group_id),
        }
        total = db["Orders"].count_documents(base_match)
        canceled = db["Orders"].count_documents({**base_match, "status": "CANCELED"})
        received = db["Orders"].count_documents({**base_match, "status": "RECIEVED"})

        gmv_over_time_pipeline = [
            {"$match": base_match},
            _coerce_date_add_fields("created_at", "_normalizedDate"),
            {"$match": {"_normalizedDate": {"$exists": True, "$ne": None}}},
            {
                "$group": {
                    "_id": _date_to_string_group_id("_normalizedDate", granularity),
                    "gmv": {"$sum": {"$ifNull": ["$offer.price", 0]}},
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        gmv_over_time = [
            {"period": row["_id"], "gmv": round(row["gmv"] or 0, 2), "count": row["count"]}
            for row in db["Orders"].aggregate(gmv_over_time_pipeline)
            if row.get("_id")
        ]

        fulfillment_pipeline = [
            {"$match": base_match},
            {"$group": {"_id": "$part_request.fulfillment_type", "count": {"$sum": 1}}},
        ]
        fulfillment = [
            {"key": row["_id"], "count": row["count"]}
            for row in db["Orders"].aggregate(fulfillment_pipeline)
        ]

        top_buyers_pipeline = [
            {"$match": base_match},
            {"$group": {"_id": "$group", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top_buyers = [
            {"group_id": row["_id"], "count": row["count"]}
            for row in db["Orders"].aggregate(top_buyers_pipeline)
        ]

        top_sellers_pipeline = [
            {"$match": base_match},
            {"$group": {"_id": "$offer.group_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top_sellers = [
            {"group_id": row["_id"], "count": row["count"]}
            for row in db["Orders"].aggregate(top_sellers_pipeline)
        ]

        return {
            "total": total,
            "by_status": _count_by_field("Orders", "status", base_match),
            "created_over_time": _time_series("Orders", "created_at", base_match, granularity),
            "gmv_over_time": gmv_over_time,
            "cancellation_rate_percent": round((canceled / total * 100) if total else 0, 2),
            "received_rate_percent": round((received / total * 100) if total else 0, 2),
            "fulfillment_split": fulfillment,
            "top_buyer_groups": top_buyers,
            "top_seller_groups": top_sellers,
        }

    @staticmethod
    def get_users_metrics(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        base_match = _date_match("createdAt", date_from, date_to)
        total = db["Users"].count_documents({})

        role_pipeline = [
            {"$unwind": {"path": "$roles", "preserveNullAndEmptyArrays": False}},
            {"$group": {"_id": "$roles", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        by_role = [
            {"role": row["_id"], "count": row["count"]}
            for row in db["Users"].aggregate(role_pipeline)
        ]

        return {
            "total": total,
            "by_global_role": by_role,
            "user_roles_assignments": {
                "active": db["UserRoles"].count_documents({"active": True}),
                "inactive": db["UserRoles"].count_documents({"active": False}),
            },
            "new_over_time": _time_series("Users", "createdAt", base_match, "day"),
        }

    @staticmethod
    def get_groups_metrics(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        total = db["groups"].count_documents({})
        active = db["groups"].count_documents({"isActive": True})
        by_type = _count_by_field("groups", "type", {})
        call_centers = db["groups"].count_documents({"is_callcenter": True})
        commissioners = db["groups"].count_documents({"is_commissioner": True})

        return {
            "total": total,
            "active": active,
            "inactive": total - active,
            "by_type": by_type,
            "call_centers": call_centers,
            "commissioners": commissioners,
        }

    @staticmethod
    def get_roles_metrics() -> Dict[str, Any]:
        catalog_size = db["Roles"].count_documents({})
        assignments_active = db["UserRoles"].count_documents({"active": True})
        assignments_inactive = db["UserRoles"].count_documents({"active": False})

        by_role_pipeline = [
            {"$group": {"_id": "$role", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        by_role = [
            {"role": row["_id"], "count": row["count"]}
            for row in db["UserRoles"].aggregate(by_role_pipeline)
        ]

        by_group_pipeline = [
            {"$match": {"group": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$group", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        by_group = [
            {"group_id": row["_id"], "count": row["count"]}
            for row in db["UserRoles"].aggregate(by_group_pipeline)
        ]

        return {
            "catalog_size": catalog_size,
            "assignments_active": assignments_active,
            "assignments_inactive": assignments_inactive,
            "assignments_by_role": by_role,
            "top_groups_by_assignments": by_group,
        }

    @staticmethod
    def get_pending_carts_metrics() -> Dict[str, Any]:
        total = db["pending_carts"].count_documents({})
        pipeline = [
            {
                "$project": {
                    "part_count": {"$size": {"$ifNull": ["$part_list", []]}},
                    "group_id": 1,
                }
            },
            {"$group": {"_id": None, "avg_parts": {"$avg": "$part_count"}}},
        ]
        avg_parts_result = list(db["pending_carts"].aggregate(pipeline))
        avg_parts = avg_parts_result[0]["avg_parts"] if avg_parts_result else 0

        by_group_pipeline = [
            {"$group": {"_id": "$group_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        by_group = [
            {"group_id": row["_id"], "count": row["count"]}
            for row in db["pending_carts"].aggregate(by_group_pipeline)
        ]

        return {
            "total_open_carts": total,
            "avg_parts_per_cart": round(avg_parts or 0, 2),
            "by_group": by_group,
        }

    @staticmethod
    def get_group_vehicles_metrics() -> Dict[str, Any]:
        total = db["GroupCars"].count_documents({})
        active = db["GroupCars"].count_documents({"active": True})

        top_makers_pipeline = [
            {"$group": {"_id": "$maker", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top_makers = [
            {"maker": row["_id"], "count": row["count"]}
            for row in db["GroupCars"].aggregate(top_makers_pipeline)
        ]

        top_models_pipeline = [
            {"$group": {"_id": "$model", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top_models = [
            {"model": row["_id"], "count": row["count"]}
            for row in db["GroupCars"].aggregate(top_models_pipeline)
        ]

        avg_requests_pipeline = [
            {"$group": {"_id": None, "avg": {"$avg": {"$ifNull": ["$numberOfRequests", 0]}}}},
        ]
        avg_requests = list(db["GroupCars"].aggregate(avg_requests_pipeline))
        avg_requests_value = avg_requests[0]["avg"] if avg_requests else 0

        return {
            "total": total,
            "active": active,
            "inactive": total - active,
            "top_makers": top_makers,
            "top_models": top_models,
            "avg_requests_per_vehicle": round(avg_requests_value or 0, 2),
        }

    @staticmethod
    def get_catalogs_metrics() -> Dict[str, Any]:
        brands_total = db["Brands"].count_documents({})
        guarantees_total = db["Guarantees"].count_documents({})

        brand_usage_pipeline = [
            {"$match": {"brand": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$brand", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        brand_usage = [
            {"label": row["_id"], "offer_count": row["count"]}
            for row in db["Offers"].aggregate(brand_usage_pipeline)
        ]

        guarantee_usage_pipeline = [
            {"$match": {"guarantee": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$guarantee", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        guarantee_usage = [
            {"label": row["_id"], "offer_count": row["count"]}
            for row in db["Offers"].aggregate(guarantee_usage_pipeline)
        ]

        return {
            "brands_total": brands_total,
            "guarantees_total": guarantees_total,
            "top_brands_by_usage": brand_usage,
            "top_guarantees_by_usage": guarantee_usage,
        }

    # ── Paginated list views ────────────────────────────────────────────────

    @staticmethod
    def list_part_requests(
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        group_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if status:
            match["status"] = status
        if group_id:
            match["creatorGroup"] = group_id
        if search:
            match["$or"] = [
                {"part": {"$regex": search, "$options": "i"}},
                {"vehicleInformation.maker": {"$regex": search, "$options": "i"}},
            ]
        return _paginate("PartRequests", match, page, page_size)

    @staticmethod
    def list_offers(
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if status:
            match["status"] = status
        if group_id:
            match["group_id"] = group_id
        return _paginate("Offers", match, page, page_size)

    @staticmethod
    def list_orders(
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if status:
            match["status"] = status
        if group_id:
            match["group"] = group_id
        return _paginate("Orders", match, page, page_size, sort_field="created_at")

    @staticmethod
    def list_users(
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if search:
            match["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
                {"uid": {"$regex": search, "$options": "i"}},
                {"phone": {"$regex": search, "$options": "i"}},
            ]
        return _paginate("Users", match, page, page_size, sort_field="name")

    @staticmethod
    def list_groups(
        page: int = 1,
        page_size: int = 20,
        group_type: Optional[int] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if group_type is not None:
            match["type"] = group_type
        if search:
            match["name"] = {"$regex": search, "$options": "i"}
        return _paginate("groups", match, page, page_size, sort_field="name")

    @staticmethod
    def list_roles_catalog() -> List[Dict[str, Any]]:
        return _serialize_docs(list(db["Roles"].find({}).sort("description", 1)))

    @staticmethod
    def _enrich_user_role_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not items:
            return items

        role_labels = {
            str(row.get("value")): row.get("description")
            for row in db["Roles"].find({}, {"value": 1, "description": 1})
        }

        group_ids: List[ObjectId] = []
        user_uids: List[str] = []
        for item in items:
            group_id = item.get("group")
            if group_id:
                try:
                    group_ids.append(ObjectId(group_id))
                except InvalidId:
                    pass
            if item.get("user_uid"):
                user_uids.append(str(item["user_uid"]))

        group_names: Dict[str, str] = {}
        if group_ids:
            for group in db["groups"].find({"_id": {"$in": group_ids}}, {"name": 1}):
                group_names[str(group["_id"])] = group.get("name") or str(group["_id"])

        user_names: Dict[str, str] = {}
        if user_uids:
            for user in db["Users"].find({"uid": {"$in": user_uids}}, {"uid": 1, "name": 1, "email": 1}):
                user_names[user["uid"]] = user.get("name") or user.get("email") or user["uid"]

        enriched: List[Dict[str, Any]] = []
        for item in items:
            row = dict(item)
            role_code = str(row.get("role") or "")
            row["role_description"] = role_labels.get(role_code)
            group_id = row.get("group")
            row["group_name"] = group_names.get(str(group_id)) if group_id else None
            row["user_name"] = user_names.get(str(row.get("user_uid")))
            enriched.append(row)
        return enriched

    @staticmethod
    def list_user_roles(
        page: int = 1,
        page_size: int = 20,
        user_uid: Optional[str] = None,
        group_id: Optional[str] = None,
        role: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if user_uid:
            match["user_uid"] = user_uid
        if group_id:
            match["group"] = group_id
        if role:
            match["role"] = role
        if active is not None:
            match["active"] = active
        result = _paginate("UserRoles", match, page, page_size, sort_field="created_at")
        result["items"] = AdminMetricsService._enrich_user_role_items(result["items"])
        return result

    @staticmethod
    def list_pending_carts(
        page: int = 1,
        page_size: int = 20,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if group_id:
            match["group_id"] = group_id
        return _paginate("pending_carts", match, page, page_size, sort_field="updated_at")

    @staticmethod
    def list_guarantees(
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if search:
            match["label"] = {"$regex": search, "$options": "i"}
        return _paginate("Guarantees", match, page, page_size, sort_field="label")

    @staticmethod
    def list_brands(
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if search:
            match["label"] = {"$regex": search, "$options": "i"}
        return _paginate("Brands", match, page, page_size, sort_field="label")

    @staticmethod
    def list_group_vehicles(
        page: int = 1,
        page_size: int = 20,
        group_id: Optional[str] = None,
        maker: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        match: Dict[str, Any] = {}
        if group_id:
            match["group"] = group_id
        if maker:
            match["maker"] = {"$regex": maker, "$options": "i"}
        if active is not None:
            match["active"] = active
        return _paginate("GroupCars", match, page, page_size, sort_field="createdAt")
