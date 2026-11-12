"""Single role -> permission check for per-group capabilities."""

from typing import Dict

from bson.errors import InvalidId

from app.dependencies import group_auth
from app.repositories import UserRolesRepository as userRolesRepository

PERMISSION_WHATSAPP_CREATE_DRAFT = "whatsapp.create_draft"

ROLE_PERMISSIONS: Dict[str, frozenset] = {
    "212": frozenset({PERMISSION_WHATSAPP_CREATE_DRAFT}),
    "213": frozenset({PERMISSION_WHATSAPP_CREATE_DRAFT}),
}


def can(uid: str, group_id: str, permission: str) -> bool:
    """True when the user is a member of the group and the owner or holds an
    active role granting `permission`. Malformed group ids yield False."""
    if not uid or not group_id:
        return False
    try:
        if not group_auth.user_belongs_to_group(uid, group_id):
            return False
        if group_auth.is_group_owner(uid, group_id):
            return True
        rows = userRolesRepository.find(
            {"user_uid": uid, "group": group_id, "active": True}
        )
    except InvalidId:
        return False
    return any(permission in ROLE_PERMISSIONS.get(str(r.role), ()) for r in rows)
