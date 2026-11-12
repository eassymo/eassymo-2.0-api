"""One-off migration of legacy users.pos_whatsapp into per-group WhatsappLinks."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.repositories import GroupRepository as groupRepository
from app.repositories import UserRepository as userRepository
from app.repositories import UserRolesRepository as userRolesRepository
from app.repositories import WhatsappLinkRepository as link_repo
from app.services.access_policy import can, PERMISSION_WHATSAPP_CREATE_DRAFT
from app.utils.phone_normalize import canonical_pos_phone


def mask_phone(phone: str) -> str:
    return "***" + phone[-4:]


def _parse_verified_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _denial_reason(uid: str, group_id: str) -> str:
    rows = userRolesRepository.find(
        {"user_uid": uid, "group": group_id, "active": True}
    )
    return "role_not_allowed" if rows else "no_role_row"


def migrate(apply: bool) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "created": 0,
        "existing": 0,
        "skipped_no_access": [],
        "invalid_phones": [],
        "phone_conflicts": [],
    }
    by_phone: Dict[str, List[dict]] = defaultdict(list)
    for user in userRepository.find({"pos_whatsapp": {"$nin": [None, ""]}}, limit=0):
        uid = user.get("uid")
        raw = user.get("pos_whatsapp")
        if not uid or not raw or not str(raw).strip():
            continue
        try:
            canonical = canonical_pos_phone(str(raw))
        except ValueError:
            report["invalid_phones"].append(uid)
            continue
        by_phone[canonical].append(user)

    for phone, owners in by_phone.items():
        if len({o["uid"] for o in owners}) > 1:
            report["phone_conflicts"].append(mask_phone(phone))
            continue
        user = owners[0]
        uid = user["uid"]
        verified_at = _parse_verified_at(user.get("pos_whatsapp_verified_at"))
        for group in groupRepository.find_by_user(uid):
            group_id = str(group["_id"])
            if not can(uid, group_id, PERMISSION_WHATSAPP_CREATE_DRAFT):
                report["skipped_no_access"].append(
                    {
                        "uid": uid,
                        "group_id": group_id,
                        "reason": _denial_reason(uid, group_id),
                    }
                )
                continue
            if not apply:
                report["created"] += 1
                continue
            if link_repo.insert_if_absent(uid, group_id, phone, verified_at):
                report["created"] += 1
            else:
                report["existing"] += 1
    return report
