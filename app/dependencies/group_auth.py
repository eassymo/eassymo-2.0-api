"""Group membership and owner authorization helpers."""

from typing import Optional

from fastapi import HTTPException, Request, status

from app.repositories import GroupRepository as groupRepository
from app.repositories import UserRolesRepository as userRolesRepository
from app.repositories import UserRepository as userRepository


def _caller_uid(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if not user or not user.get("uid"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )
    return str(user["uid"])


def get_group_owner_uid(group_id: str) -> Optional[str]:
    if not group_id or not str(group_id).strip():
        return None
    group_doc = groupRepository.find_by_id(str(group_id).strip())
    if not group_doc:
        return None
    owner = group_doc.get("owner")
    return str(owner) if owner else None


def is_group_owner(caller_uid: str, group_id: str) -> bool:
    owner_uid = get_group_owner_uid(group_id)
    if not owner_uid:
        return False
    return str(caller_uid) == owner_uid


def user_belongs_to_group(user_uid: str, group_id: str) -> bool:
    if not user_uid or not group_id:
        return False

    group_doc = groupRepository.find_by_id(str(group_id).strip())
    if group_doc:
        users = group_doc.get("users") or []
        if str(user_uid) in [str(u) for u in users]:
            return True
        owner = group_doc.get("owner")
        if owner and str(owner) == str(user_uid):
            return True

    user_doc = userRepository.find_one({"uid": user_uid})
    if user_doc:
        groups = user_doc.get("groups") or []
        if str(group_id) in [str(g) for g in groups]:
            return True

    active_roles = userRolesRepository.find(
        {"user_uid": user_uid, "group": str(group_id), "active": True}
    )
    return len(active_roles) > 0


def assert_group_membership(caller_uid: str, group_id: str) -> None:
    if not group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GroupSelected header or group_id is required",
        )
    if not user_belongs_to_group(caller_uid, group_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to this group",
        )


def assert_group_owner(caller_uid: str, group_id: str) -> None:
    if not group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="group is required",
        )
    if not is_group_owner(caller_uid, group_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner may perform this action",
        )


def authorize_role_mutation(
    request: Request,
    target_user_uid: str,
    group_id: Optional[str],
) -> None:
    """
    Group owner may manage roles for members; new shop owner may assign own first role.
    """
    caller_uid = _caller_uid(request)
    target_user_uid = str(target_user_uid).strip()
    group_id_str = str(group_id).strip() if group_id else None

    if group_id_str:
        if is_group_owner(caller_uid, group_id_str):
            return
        if caller_uid == target_user_uid and is_group_owner(caller_uid, group_id_str):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner may manage roles for this group",
        )

    # Pre-group role row (onboarding): caller may only create for themselves
    if caller_uid != target_user_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot assign roles to another user without a group context",
        )


def require_group_membership_from_header(request: Request) -> str:
    """Validate GroupSelected header and membership; return group id."""
    caller_uid = _caller_uid(request)
    group_id = getattr(request.state, "groupSelected", None)
    if not group_id:
        group_id = request.headers.get("groupselected")
    assert_group_membership(caller_uid, str(group_id))
    return str(group_id)


def require_authenticated_uid(request: Request) -> str:
    return _caller_uid(request)
