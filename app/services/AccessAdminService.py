"""Super-admin "Accesos" module: manage grants and roles, check a user's access."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import HTTPException, status

from app.authz.grant_keys import EASSYMO_PREFIX
from app.authz.grant_sections import GRANT_SECTIONS
from app.config import database
from app.dependencies import group_auth
from app.repositories.RolesRepository import value_variants
from app.schemas.Grant import EDITABLE_GRANT_FIELDS
from app.services import authz

POVS = {"vendedor", "comprador", "ambos"}
ENTITY_TYPES = {"1", "2", "3", "4"}
FUNCTIONS = {"admin", "vendedor", "gestor", "almacenista", "repartidor", "mecanico", "comprador", "legacy"}
ROLE_FIELDS = {"description", "grants", "pov", "entity_types", "function", "assignable_by_group_admins", "active"}
OWNER_SOURCE = "dueño"


def _db():
    return database.db


def _find(collection: str, *args) -> List[dict]:
    """Always materialize: pymongo cursors are one-pass and always truthy."""
    return list(_db()[collection].find(*args))


def _now():
    return datetime.now(timezone.utc)


def _log(admin_uid: str, action: str, entity_type: str, entity_id: str, payload: Optional[dict] = None):
    _db()["AdminAuditLog"].insert_one({
        "admin_uid": admin_uid,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload or {},
        "created_at": _now(),
    })


def _clean(doc: dict) -> dict:
    """Drop `_id` and make every datetime JSON-safe (created_at, updated_at, captured_at…)."""
    return {
        k: (v.isoformat() if isinstance(v, datetime) else v)
        for k, v in doc.items() if k != "_id"
    }


def _active_holders(role_values) -> List[dict]:
    values = list(role_values)
    if not values:
        return []
    return _find("UserRoles", {"role": {"$in": value_variants(values)}, "active": True}, {"user_uid": 1, "group": 1, "role": 1})


def _impact(rows) -> Dict[str, int]:
    return {
        "users": len({r["user_uid"] for r in rows}),
        "groups": len({r.get("group") for r in rows if r.get("group")}),
    }


# ── Grants ──────────────────────────────────────────────────────────────────

def _sin_efecto(grant: dict) -> bool:
    """No API endpoint or app section checks this grant yet (see app/authz/grant_sections.py)."""
    return grant["key"] not in GRANT_SECTIONS


def list_grants() -> List[dict]:
    roles = _find("Roles", {}, {"grants": 1})
    roles_count = defaultdict(int)
    for role in roles:
        for key in set(role.get("grants") or []):
            roles_count[key] += 1
    grants = sorted(_find("grants", {}), key=lambda g: g.get("sort_order", 0))
    frames = {f["code"]: f for f in _find("frames", {})}

    def frame_summaries(grant):
        return [
            {"code": c, "name": frames[c].get("name"), "status": frames[c].get("status"),
             "screenshot_url": frames[c].get("screenshot_url"),
             "needs_update": bool(frames[c].get("needs_update"))}
            for c in grant.get("frame_refs") or [] if c in frames
        ]

    return [
        {
            **_clean(g),
            "roles_count": roles_count[g["key"]],
            "sections": GRANT_SECTIONS.get(g["key"], []),
            "frames": frame_summaries(g),
            "sin_efecto": _sin_efecto(g),
        }
        for g in grants
    ]


def update_grant(admin_uid: str, key: str, data: Dict[str, Any]) -> dict:
    invalid = set(data) - EDITABLE_GRANT_FIELDS
    if invalid:
        raise HTTPException(status_code=400, detail=f"Campos no editables: {', '.join(sorted(invalid))}")
    before = _db()["grants"].find_one({"key": key})
    if not before:
        raise HTTPException(status_code=404, detail="Permiso no encontrado")
    if "frame_refs" in data:
        refs = [str(c) for c in (data["frame_refs"] or [])]
        known = {f["code"] for f in _find("frames", {"code": {"$in": refs}}, {"code": 1})}
        unknown = [c for c in refs if c not in known]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Frames desconocidos: {', '.join(unknown)}")
        data = {**data, "frame_refs": list(dict.fromkeys(refs))}
    fields = {**data, "updated_at": _now(), "updated_by": admin_uid}
    _db()["grants"].update_one({"key": key}, {"$set": fields})
    _log(admin_uid, "update_grant", "grant", key,
         {"before": {k: before.get(k) for k in data}, "after": data})
    return _clean(_db()["grants"].find_one({"key": key}))


def grant_impact(key: str) -> Dict[str, int]:
    values = [r["value"] for r in _find("Roles", {"grants": key}, {"value": 1})]
    return _impact(_active_holders(values))


# ── Roles ───────────────────────────────────────────────────────────────────

def _validate_role(data: Dict[str, Any], current: Optional[dict] = None) -> Dict[str, Any]:
    invalid = set(data) - ROLE_FIELDS
    if invalid:
        raise HTTPException(status_code=400, detail=f"Campos no editables: {', '.join(sorted(invalid))}")
    merged = {**(current or {}), **data}
    pov = merged.get("pov")
    if pov not in POVS:
        raise HTTPException(status_code=400, detail="POV inválido (vendedor, comprador o ambos)")
    if not str(merged.get("description") or "").strip():
        raise HTTPException(status_code=400, detail="El nombre del rol es obligatorio")
    entity_types = [str(t) for t in (merged.get("entity_types") or [])]
    if set(entity_types) - ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de negocio inválido")
    if merged.get("function") is not None and merged.get("function") not in FUNCTIONS:
        raise HTTPException(status_code=400, detail="Función inválida")
    grants = sorted(set(merged.get("grants") or []))
    catalog = {g["key"]: g for g in _find("grants", {"key": {"$in": grants}})}
    for key in grants:
        if key.startswith(EASSYMO_PREFIX):
            raise HTTPException(status_code=400, detail=f"{key} es exclusivo de Eassymo")
        if key not in catalog:
            raise HTTPException(status_code=400, detail=f"Permiso desconocido: {key}")
        grant_pov = catalog[key].get("pov")
        if pov != "ambos" and grant_pov not in ("ambos", pov):
            raise HTTPException(status_code=400, detail=f"{key} no corresponde al POV {pov}")
    out = {k: v for k, v in data.items() if k in ROLE_FIELDS}
    if "grants" in data:
        out["grants"] = grants
    if "entity_types" in data:
        out["entity_types"] = entity_types
    return out


def _by_value(value) -> dict:
    return {"value": {"$in": value_variants([value])}}


def _role_or_404(value: str) -> dict:
    role = _db()["Roles"].find_one(_by_value(value))
    if not role:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    return role


def _role_grants(role: dict) -> List[str]:
    """The Super Admin role (all_grants) holds every grant in the catalog, now and later."""
    if role.get("all_grants"):
        return sorted(g["key"] for g in _find("grants", {"active": {"$ne": False}}, {"key": 1}))
    return sorted(role.get("grants") or [])


def _with_counts(role: dict, rows_by_role: Dict[str, list]) -> dict:
    rows = rows_by_role.get(str(role.get("value")), [])
    impact = _impact(rows)
    grants = _role_grants(role)
    return {
        **_clean(role),
        "grants": grants,
        "grants_count": len(grants),
        "users_count": impact["users"],
        "groups_count": impact["groups"],
    }


def list_roles(filters: Dict[str, Any]) -> List[dict]:
    query: Dict[str, Any] = {}
    if filters.get("pov"):
        query["pov"] = filters["pov"]
    if filters.get("function"):
        query["function"] = filters["function"]
    if filters.get("entity_type"):
        query["entity_types"] = str(filters["entity_type"])
    if filters.get("kind") == "system":
        query["is_system"] = True
    elif filters.get("kind") == "custom":
        query["is_system"] = {"$ne": True}
    roles = _find("Roles", query)
    rows_by_role = defaultdict(list)
    for row in _active_holders([r["value"] for r in roles if r.get("value") is not None]):
        rows_by_role[str(row["role"])].append(row)
    out = [_with_counts(r, rows_by_role) for r in roles]
    return sorted(out, key=lambda r: (not r.get("is_system"), r.get("pov") or "", r.get("description") or ""))


def create_role(admin_uid: str, data: Dict[str, Any]) -> dict:
    fields = _validate_role({k: v for k, v in data.items() if k in ROLE_FIELDS})
    value = f"r_{uuid4().hex[:8]}"
    doc = {
        "value": value,
        "grants": [],
        "entity_types": [],
        "function": None,
        "assignable_by_group_admins": False,
        "active": True,
        **fields,
        "is_system": False,
        "display": False,
        "created_at": _now(),
        "updated_at": _now(),
        "updated_by": admin_uid,
    }
    _db()["Roles"].insert_one(doc)
    _log(admin_uid, "create_access_role", "role", value, {"after": doc["grants"]})
    return _with_counts(_db()["Roles"].find_one({"value": value}), {})


def update_role(admin_uid: str, value: str, data: Dict[str, Any]) -> dict:
    current = _role_or_404(value)
    if current.get("all_grants") and "grants" in data:
        raise HTTPException(status_code=400, detail="El rol Super Admin siempre tiene todos los permisos")
    fields = _validate_role(data, current)
    _db()["Roles"].update_one({"_id": current["_id"]}, {"$set": {**fields, "updated_at": _now(), "updated_by": admin_uid}})
    _log(admin_uid, "update_access_role", "role", value, {
        "before": sorted(current.get("grants") or []),
        "after": sorted(fields.get("grants", current.get("grants") or [])),
        "fields": sorted(fields),
    })
    rows = _active_holders([value])
    return _with_counts(_db()["Roles"].find_one({"_id": current["_id"]}), {str(current["value"]): rows})


def delete_role(admin_uid: str, value: str) -> dict:
    role = _role_or_404(value)
    if role.get("is_system"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Los roles del sistema no se pueden eliminar")
    if _active_holders([value]):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El rol tiene usuarios asignados")
    _db()["Roles"].delete_one({"_id": role["_id"]})
    _log(admin_uid, "delete_access_role", "role", value, {"before": sorted(role.get("grants") or [])})
    return {"deleted": value}


def duplicate_role(admin_uid: str, value: str) -> dict:
    role = _role_or_404(value)
    data = {k: role.get(k) for k in ROLE_FIELDS if role.get(k) is not None}
    data["description"] = f"{role.get('description') or value} (copia)"
    if data.get("pov") not in POVS:
        data["pov"] = "ambos"
    return create_role(admin_uid, data)


def role_impact(value: str) -> Dict[str, int]:
    _role_or_404(value)
    return _impact(_active_holders([value]))


# ── Access check & metrics ──────────────────────────────────────────────────

def access_check(uid: str, group_id: str) -> dict:
    is_member = bool(group_auth.user_belongs_to_group(uid, group_id))
    is_owner = is_member and bool(group_auth.is_group_owner(uid, group_id))
    grants = authz.effective_grants(uid, group_id)
    sources = defaultdict(list)
    rows = _find("UserRoles", {"user_uid": uid, "group": group_id, "active": True}, {"role": 1})
    values = sorted({str(r["role"]) for r in rows})
    roles = _find("Roles", {"value": {"$in": value_variants(values)}})
    for role in roles:
        for key in (grants if role.get("all_grants") else role.get("grants") or []):
            if key in grants:
                sources[key].append(str(role["value"]))
    if is_owner:
        for key in grants:
            if not key.startswith(EASSYMO_PREFIX):
                sources[key].insert(0, OWNER_SOURCE)
    catalog = [g["key"] for g in _find("grants", {"active": {"$ne": False}})]
    return {
        "uid": uid,
        "group_id": group_id,
        "is_member": is_member,
        "is_owner": is_owner,
        "grants": [{"key": k, "sources": sorted(sources[k])} for k in sorted(grants)],
        "missing": sorted(k for k in catalog if k not in grants and not k.startswith(EASSYMO_PREFIX)),
    }


def metrics() -> dict:
    roles = _find("Roles", {})
    template_values = [r["value"] for r in roles if r.get("function") not in (None, "legacy") and r.get("value")]
    legacy_values = [r["value"] for r in roles if r.get("function") == "legacy"]
    grants = _find("grants", {})
    return {
        "active_roles": sum(1 for r in roles if r.get("active", True) is not False),
        "active_grants": sum(1 for g in grants if g.get("active", True) is not False),
        "users_template_roles": len({r["user_uid"] for r in _active_holders(template_values)}),
        "users_legacy_roles": len({r["user_uid"] for r in _active_holders(legacy_values)}),
        "sin_efecto": sum(1 for g in grants if _sin_efecto(g)),
    }
