"""Grant-based authorization.

A user's effective grants in a group are the union of the grants of their active
roles in that group, limited to active grants. The group owner holds every active
grant. `eassymo.*` grants are never given through a group role or ownership.
"""

from typing import Iterable, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, Request, status

from app.authz.grant_keys import (
    ALL_KEYS,
    DELIVERIES_PERFORM,
    EASSYMO_PREFIX,
    ORDERS_CHANGE_STATUS,
    TEAM_ASSIGN_ROLES,
    TEAM_INVITE,
)
from app.authz.legacy_roles import legacy_grants
from app.dependencies import group_auth
from app.repositories import GrantRepository
from app.repositories import GroupRepository as groupRepository
from app.repositories import RolesRepository
from app.repositories import UserRolesRepository as userRolesRepository

_CACHE_ATTR = "_grants_cache"


def _is_active(doc: dict) -> bool:
    return doc.get("active", True) is not False


def _assignable_keys(keys: Iterable[str]) -> frozenset:
    return frozenset(k for k in keys if not k.startswith(EASSYMO_PREFIX))


def _active_catalog_keys() -> set:
    """Active grant keys. Before scripts/seed_grants.py has run the collection is empty:
    then every key the code knows counts as active, so deploy order cannot lock people out."""
    active = GrantRepository.active_keys()
    if active or GrantRepository.find({}):
        return active
    return set(ALL_KEYS)


def _compute(uid: str, group_id: str) -> frozenset:
    try:
        if not group_auth.user_belongs_to_group(uid, group_id):
            return frozenset()
        active = _active_catalog_keys()
        is_owner = group_auth.is_group_owner(uid, group_id)
        rows = userRolesRepository.find({"user_uid": uid, "group": group_id, "active": True})
    except InvalidId:
        return frozenset()
    values = sorted({str(r.role) for r in rows})
    roles = [r for r in (RolesRepository.find_by_values(values) if values else []) if _is_active(r)]
    # The Super Admin role (all_grants) sees everything, Eassymo grants included, and keeps
    # covering grants added later.
    if any(r.get("all_grants") for r in roles):
        return frozenset(active)
    if is_owner:
        return _assignable_keys(active)
    granted = set()
    for role in roles:
        if "grants" in role:
            granted.update(role.get("grants") or [])
        else:
            # Legacy role not migrated yet: keep today's access.
            granted.update(legacy_grants(role.get("value")) or [])
    return _assignable_keys(granted & active)


def effective_grants(uid: Optional[str], group_id: Optional[str], request: Optional[Request] = None) -> frozenset:
    if not uid or not group_id:
        return frozenset()
    uid, group_id = str(uid), str(group_id)
    cache = None
    if request is not None:
        cache = getattr(request.state, _CACHE_ATTR, None)
        if cache is None:
            cache = {}
            setattr(request.state, _CACHE_ATTR, cache)
        if (uid, group_id) in cache:
            return cache[(uid, group_id)]
    grants = _compute(uid, group_id)
    if cache is not None:
        cache[(uid, group_id)] = grants
    return grants


def can(uid: Optional[str], group_id: Optional[str], key: str, request: Optional[Request] = None) -> bool:
    return key in effective_grants(uid, group_id, request)


def caller_uid(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if not user or not user.get("uid"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not authenticated")
    return str(user["uid"])


def selected_group(request: Request, override: Optional[str] = None) -> str:
    group_id = override or getattr(request.state, "groupSelected", None) or request.headers.get("groupselected")
    group_id = str(group_id).strip() if group_id else ""
    if not group_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GroupSelected header or group_id is required")
    if not ObjectId.is_valid(group_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La tienda seleccionada no es válida.")
    return group_id


def require_grant(*keys: str):
    """FastAPI dependency: the caller must hold every key in the selected group. Returns the group id."""

    def dependency(request: Request) -> str:
        uid = caller_uid(request)
        group_id = selected_group(request)
        grants = effective_grants(uid, group_id, request)
        for key in keys:
            if key not in grants:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing grant: {key}")
        return group_id

    return dependency


def resolve_role_value(role_ref) -> Optional[str]:
    """Team invites store the Roles `_id`; role mutations use the role `value`. Accept both."""
    if not role_ref:
        return None
    ref = str(role_ref).strip()
    if ObjectId.is_valid(ref):
        doc = RolesRepository.find_by_id(ref)
        return str(doc["value"]) if doc and doc.get("value") is not None else None
    return ref


def role_fits_group(group_id: str, role_value: str) -> Tuple[Optional[dict], str]:
    """The role exists, is active, has no Eassymo grants and fits the group's business type.
    Returns (role, "") or (None, reason)."""
    role = RolesRepository.find_by_value(str(role_value)) if role_value else None
    if not role or not _is_active(role):
        return None, "El rol no existe o está inactivo"
    if role.get("all_grants") or any(k.startswith(EASSYMO_PREFIX) for k in (role.get("grants") or [])):
        return None, "El rol contiene permisos exclusivos de Eassymo"
    try:
        group = groupRepository.find_by_id(group_id, {"type": 1})
    except InvalidId:
        return None, "La tienda seleccionada no es válida."
    if not group:
        return None, "La tienda no existe"
    entity_types = [str(t) for t in (role.get("entity_types") or [])]
    if entity_types and str(group.get("type")) not in entity_types:
        return None, "El rol no corresponde al tipo de negocio"
    return role, ""


def _check_delegation(
    uid: str, group_id: str, role_value: str, required_grant: str, request: Optional[Request]
) -> Tuple[bool, str]:
    role, reason = role_fits_group(group_id, role_value)
    if not role:
        return False, reason
    # The owner manages every role that fits the group, as before phase 1.
    if group_auth.is_group_owner(uid, group_id):
        return True, ""
    if not role.get("assignable_by_group_admins"):
        return False, "El rol no es asignable por administradores de grupo"
    grants = effective_grants(uid, group_id, request)
    if required_grant not in grants:
        return False, f"Missing grant: {required_grant}"
    missing = sorted(set(role.get("grants") or []) - grants)
    if missing:
        return False, "No puedes dar un rol con permisos que no tienes: " + ", ".join(missing)
    return True, ""


def can_assign_role(
    admin_uid: str, group_id: str, role_value: str, request: Optional[Request] = None
) -> Tuple[bool, str]:
    """Whether `admin_uid` may give (or remove) `role_value` in `group_id`.
    Owner: any role that fits the group. Others: team.assign_roles, an assignable role,
    and no grant they don't hold themselves."""
    return _check_delegation(admin_uid, group_id, role_value, TEAM_ASSIGN_ROLES, request)


def can_invite_with_role(
    inviter_uid: str, group_id: str, role_value: str, request: Optional[Request] = None
) -> Tuple[bool, str]:
    """Whether `inviter_uid` may invite someone with `role_value`. Same as assigning, but
    gated by team.invite (every member can invite today; team.assign_roles is not required)."""
    return _check_delegation(inviter_uid, group_id, role_value, TEAM_INVITE, request)


def delivery_role_values() -> list:
    """Values of active roles that grant `deliveries.perform` (they replace the fixed role 215)."""
    docs = RolesRepository.find({"$or": [
        {"grants": DELIVERIES_PERFORM}, {"grants": {"$exists": False}}, {"all_grants": True},
    ]})

    def role_grants(d):
        if d.get("all_grants"):
            return (DELIVERIES_PERFORM,)
        # Legacy roles not migrated yet (no `grants` field) keep today's sets.
        return d.get("grants") if "grants" in d else (legacy_grants(d.get("value")) or ())

    return sorted(
        str(d["value"]) for d in docs
        if _is_active(d) and DELIVERIES_PERFORM in role_grants(d)
    )


def delivery_role_variants() -> list:
    """`delivery_role_values` in both stored forms, for UserRoles queries."""
    return RolesRepository.value_variants(delivery_role_values())


def is_delivery_restricted(grants: frozenset) -> bool:
    """Delivery-only callers may only mark their own assigned orders as received."""
    return DELIVERIES_PERFORM in grants and ORDERS_CHANGE_STATUS not in grants


def missing_catalog_keys() -> set:
    """Grant keys the code checks that are missing from the `grants` collection."""
    from app.authz.grant_keys import ALL_KEYS

    stored = {g["key"] for g in GrantRepository.find({})}
    return set(ALL_KEYS) - stored
