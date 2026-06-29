from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from firebase_admin import auth
from pymongo import ReturnDocument

from app.config import database
from app.repositories import PendingCartRepository
from app.schemas.Brand import Brand
from app.schemas.Guarantee import Guarantee
from app.schemas.UserRoles import UserRoles

db = database.db


class AdminWriteService:
    @staticmethod
    def _log_action(
        admin_uid: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        db["AdminAuditLog"].insert_one({
            "admin_uid": admin_uid,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload or {},
            "created_at": datetime.now(timezone.utc),
        })

    @staticmethod
    def _object_id(value: str) -> ObjectId:
        try:
            return ObjectId(value)
        except InvalidId as exc:
            raise HTTPException(status_code=400, detail="Invalid id") from exc

    @staticmethod
    def force_order_status(
        admin_uid: str,
        order_id: str,
        new_status: Optional[str],
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not new_status:
            raise HTTPException(status_code=400, detail="new_status is required")

        order = db["Orders"].find_one({"order_id": order_id}) or db["Orders"].find_one(
            {"_id": AdminWriteService._object_id(order_id)}
        )
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        status_change = {
            "status": new_status,
            "timestamp": datetime.now(timezone.utc),
        }
        updated = db["Orders"].find_one_and_update(
            {"_id": order["_id"]},
            {
                "$set": {"status": new_status},
                "$push": {"status_history": status_change},
            },
            return_document=ReturnDocument.AFTER,
        )
        AdminWriteService._log_action(
            admin_uid, "force_order_status", "order", str(order["_id"]),
            {"new_status": new_status, "reason": reason},
        )
        updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def force_offer_status(
        admin_uid: str,
        offer_id: str,
        new_status: Optional[str],
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not new_status:
            raise HTTPException(status_code=400, detail="new_status is required")

        offer = db["Offers"].find_one({"_id": AdminWriteService._object_id(offer_id)})
        if not offer:
            raise HTTPException(status_code=404, detail="Offer not found")

        updated = db["Offers"].find_one_and_update(
            {"_id": offer["_id"]},
            {"$set": {"status": new_status, "updatedAt": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        AdminWriteService._log_action(
            admin_uid, "force_offer_status", "offer", offer_id,
            {"new_status": new_status, "reason": reason},
        )
        updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def update_part_request(
        admin_uid: str,
        request_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        allowed = {"status", "isActive", "fulfillment_type"}
        update_payload = {k: v for k, v in data.items() if k in allowed}
        if not update_payload:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        pr = db["PartRequests"].find_one({"_id": AdminWriteService._object_id(request_id)})
        if not pr:
            raise HTTPException(status_code=404, detail="Part request not found")

        update_payload["updatedAt"] = datetime.now(timezone.utc)
        updated = db["PartRequests"].find_one_and_update(
            {"_id": pr["_id"]},
            {"$set": update_payload},
            return_document=ReturnDocument.AFTER,
        )
        AdminWriteService._log_action(
            admin_uid, "update_part_request", "part_request", request_id, update_payload
        )
        updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def disable_user(admin_uid: str, uid: str, reason: Optional[str] = None) -> Dict[str, Any]:
        updated = db["Users"].find_one_and_update(
            {"uid": uid},
            {"$set": {"disabled": True, "disabled_reason": reason}},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        AdminWriteService._log_action(
            admin_uid, "disable_user", "user", uid, {"reason": reason}
        )
        if "_id" in updated:
            updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def enable_user(admin_uid: str, uid: str, reason: Optional[str] = None) -> Dict[str, Any]:
        updated = db["Users"].find_one_and_update(
            {"uid": uid},
            {"$set": {"disabled": False}, "$unset": {"disabled_reason": ""}},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        AdminWriteService._log_action(
            admin_uid, "enable_user", "user", uid, {"reason": reason}
        )
        if "_id" in updated:
            updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def update_group(
        admin_uid: str,
        group_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        allowed = {"name", "isActive"}
        update_payload = {k: v for k, v in data.items() if k in allowed}
        if not update_payload:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        group = db["groups"].find_one({"_id": AdminWriteService._object_id(group_id)})
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        updated = db["groups"].find_one_and_update(
            {"_id": group["_id"]},
            {"$set": update_payload},
            return_document=ReturnDocument.AFTER,
        )
        AdminWriteService._log_action(
            admin_uid, "update_group", "group", group_id, update_payload
        )
        updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def manage_global_role(
        admin_uid: str,
        uid: str,
        role: Optional[str],
        action: str = "add",
    ) -> Dict[str, Any]:
        if not role:
            raise HTTPException(status_code=400, detail="role is required")

        if action == "add":
            updated = db["Users"].find_one_and_update(
                {"uid": uid},
                {"$addToSet": {"roles": role}},
                return_document=ReturnDocument.AFTER,
            )
        elif action == "remove":
            updated = db["Users"].find_one_and_update(
                {"uid": uid},
                {"$pull": {"roles": role}},
                return_document=ReturnDocument.AFTER,
            )
        else:
            raise HTTPException(status_code=400, detail="action must be add or remove")

        if not updated:
            raise HTTPException(status_code=404, detail="User not found")

        AdminWriteService._log_action(
            admin_uid, f"{action}_global_role", "user", uid, {"role": role}
        )
        if "_id" in updated:
            updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def assign_user_role(admin_uid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        required = ["user_uid", "role", "group"]
        for field in required:
            if not data.get(field):
                raise HTTPException(status_code=400, detail=f"{field} is required")

        payload = UserRoles(
            user_uid=data["user_uid"],
            role=data["role"],
            group=data["group"],
            active=data.get("active", True),
        )
        result = db["UserRoles"].insert_one(payload.toJson())
        AdminWriteService._log_action(
            admin_uid, "assign_user_role", "user_role", str(result.inserted_id), data
        )
        created = db["UserRoles"].find_one({"_id": result.inserted_id})
        created["_id"] = str(created["_id"])
        return created

    @staticmethod
    def set_user_role_active(
        admin_uid: str,
        assignment_id: str,
        active: bool,
    ) -> Dict[str, Any]:
        existing = db["UserRoles"].find_one(
            {"_id": AdminWriteService._object_id(assignment_id)}
        )
        if not existing:
            raise HTTPException(status_code=404, detail="User role assignment not found")

        if active and not existing.get("group"):
            raise HTTPException(
                status_code=400,
                detail="Assign a group to this UserRoles record before activating it",
            )

        updated = db["UserRoles"].find_one_and_update(
            {"_id": existing["_id"]},
            {"$set": {"active": active}},
            return_document=ReturnDocument.AFTER,
        )
        AdminWriteService._log_action(
            admin_uid, "set_user_role_active", "user_role", assignment_id, {"active": active}
        )
        updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def update_user_role(
        admin_uid: str,
        assignment_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        allowed = {"role", "group", "active"}
        update_payload = {k: v for k, v in data.items() if k in allowed}
        if not update_payload:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        existing = db["UserRoles"].find_one(
            {"_id": AdminWriteService._object_id(assignment_id)}
        )
        if not existing:
            raise HTTPException(status_code=404, detail="User role assignment not found")

        next_role = update_payload.get("role", existing.get("role"))
        next_group = update_payload.get("group", existing.get("group"))
        next_active = update_payload.get("active", existing.get("active"))

        if next_active and not next_group:
            raise HTTPException(
                status_code=400,
                detail="A UserRoles assignment must have a group before it can be active",
            )

        duplicate = db["UserRoles"].find_one({
            "user_uid": existing.get("user_uid"),
            "role": next_role,
            "group": next_group,
            "_id": {"$ne": existing["_id"]},
        })
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="This user already has that role for the selected group",
            )

        updated = db["UserRoles"].find_one_and_update(
            {"_id": existing["_id"]},
            {"$set": update_payload},
            return_document=ReturnDocument.AFTER,
        )
        AdminWriteService._log_action(
            admin_uid, "update_user_role", "user_role", assignment_id, update_payload
        )
        updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def delete_user_role(admin_uid: str, assignment_id: str) -> Dict[str, Any]:
        deleted = db["UserRoles"].find_one_and_delete(
            {"_id": AdminWriteService._object_id(assignment_id)}
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="User role assignment not found")
        AdminWriteService._log_action(
            admin_uid, "delete_user_role", "user_role", assignment_id, {}
        )
        deleted["_id"] = str(deleted["_id"])
        return deleted

    @staticmethod
    def manage_super_admin_claim(
        admin_uid: str,
        target_uid: str,
        grant: bool,
    ) -> Dict[str, Any]:
        try:
            user = auth.get_user(target_uid)
            claims = dict(user.custom_claims or {})
            if grant:
                claims["super_admin"] = True
            else:
                claims.pop("super_admin", None)
            auth.set_custom_user_claims(target_uid, claims or None)
        except auth.UserNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Firebase user not found") from exc
        except Exception as exc:
            message = str(exc)
            if "Invalid JWT Signature" in message:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Firebase Admin credentials are invalid. "
                        "Set FIREBASE_SERVICE_ACCOUNT_PATH to your service account JSON "
                        "or place the JSON file in the API project root, then restart the server."
                    ),
                ) from exc
            raise HTTPException(
                status_code=500,
                detail="Failed to update Firebase custom claims: {}".format(message),
            ) from exc

        AdminWriteService._log_action(
            admin_uid,
            "grant_super_admin" if grant else "revoke_super_admin",
            "user",
            target_uid,
            {"grant": grant},
        )
        db["Users"].update_one(
            {"uid": target_uid},
            {"$set": {"super_admin": grant}},
        )
        return {"uid": target_uid, "super_admin": grant}

    @staticmethod
    def delete_pending_cart(
        admin_uid: str,
        user_uid: str,
        group_id: str,
    ) -> Dict[str, Any]:
        deleted = PendingCartRepository.delete_by_user_and_group(user_uid, group_id)
        AdminWriteService._log_action(
            admin_uid, "delete_pending_cart", "pending_cart", user_uid,
            {"group_id": group_id, "deleted": deleted},
        )
        return {"deleted": deleted}

    @staticmethod
    def create_brand(admin_uid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        label = data.get("label")
        if not label:
            raise HTTPException(status_code=400, detail="label is required")
        brand = Brand(label=label, user_uid=admin_uid)
        result = db["Brands"].insert_one(brand.dict())
        AdminWriteService._log_action(admin_uid, "create_brand", "brand", str(result.inserted_id), data)
        created = db["Brands"].find_one({"_id": result.inserted_id})
        created["_id"] = str(created["_id"])
        return created

    @staticmethod
    def update_brand(admin_uid: str, brand_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        label = data.get("label")
        if not label:
            raise HTTPException(status_code=400, detail="label is required")
        updated = db["Brands"].find_one_and_update(
            {"_id": AdminWriteService._object_id(brand_id)},
            {"$set": {"label": label}},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Brand not found")
        AdminWriteService._log_action(admin_uid, "update_brand", "brand", brand_id, data)
        updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def delete_brand(admin_uid: str, brand_id: str) -> Dict[str, Any]:
        deleted = db["Brands"].find_one_and_delete(
            {"_id": AdminWriteService._object_id(brand_id)}
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Brand not found")
        AdminWriteService._log_action(admin_uid, "delete_brand", "brand", brand_id, {})
        deleted["_id"] = str(deleted["_id"])
        return deleted

    @staticmethod
    def create_guarantee(admin_uid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        label = data.get("label")
        if not label:
            raise HTTPException(status_code=400, detail="label is required")
        guarantee = Guarantee(label=label, user_uid=admin_uid)
        result = db["Guarantees"].insert_one(guarantee.dict())
        AdminWriteService._log_action(
            admin_uid, "create_guarantee", "guarantee", str(result.inserted_id), data
        )
        created = db["Guarantees"].find_one({"_id": result.inserted_id})
        created["_id"] = str(created["_id"])
        return created

    @staticmethod
    def update_guarantee(
        admin_uid: str,
        guarantee_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        label = data.get("label")
        if not label:
            raise HTTPException(status_code=400, detail="label is required")
        updated = db["Guarantees"].find_one_and_update(
            {"_id": AdminWriteService._object_id(guarantee_id)},
            {"$set": {"label": label}},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Guarantee not found")
        AdminWriteService._log_action(
            admin_uid, "update_guarantee", "guarantee", guarantee_id, data
        )
        updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def delete_guarantee(admin_uid: str, guarantee_id: str) -> Dict[str, Any]:
        deleted = db["Guarantees"].find_one_and_delete(
            {"_id": AdminWriteService._object_id(guarantee_id)}
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Guarantee not found")
        AdminWriteService._log_action(admin_uid, "delete_guarantee", "guarantee", guarantee_id, {})
        deleted["_id"] = str(deleted["_id"])
        return deleted

    @staticmethod
    def update_group_vehicle(
        admin_uid: str,
        vehicle_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        allowed = {"active", "maker", "model", "year", "engine", "licensePlate", "vin"}
        update_payload = {k: v for k, v in data.items() if k in allowed}
        if not update_payload:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        updated = db["GroupCars"].find_one_and_update(
            {"_id": AdminWriteService._object_id(vehicle_id)},
            {"$set": update_payload},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Group vehicle not found")
        AdminWriteService._log_action(
            admin_uid, "update_group_vehicle", "group_vehicle", vehicle_id, update_payload
        )
        updated["_id"] = str(updated["_id"])
        return updated

    @staticmethod
    def list_audit_log(page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        skip = max(page - 1, 0) * page_size
        total = db["AdminAuditLog"].count_documents({})
        cursor = (
            db["AdminAuditLog"]
            .find({})
            .sort("created_at", -1)
            .skip(skip)
            .limit(page_size)
        )
        items = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            if doc.get("created_at"):
                doc["created_at"] = doc["created_at"].isoformat()
            items.append(doc)
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max((total + page_size - 1) // page_size, 1),
        }
