"""Push notifications about WhatsApp usage limits (store managers and super admins)."""

import logging
from datetime import datetime
from typing import List, Literal, Optional

from app.authz.grant_keys import TEAM_MANAGE_MEMBERS
from app.repositories import GroupRepository as groupRepository
from app.repositories import UserRolesRepository as userRolesRepository
from app.services import push_service
from app.services.authz import can
from app.services.WhatsappUsageMessages import _renewal
from app.services.WhatsappUsageService import UsageSnapshot

logger = logging.getLogger(__name__)

NAVIGATE_URL = "/user-configuration/whatsapp-pos"
SUPER_ADMIN_ROLE = "super_admin"


class WhatsappUsageNotifier:
    def manager_uids(self, group_id: str) -> List[str]:
        """Store members (owner, listed users, active role holders) holding team.manage_members."""
        try:
            group = groupRepository.find_by_id(str(group_id)) or {}
            candidates: List[str] = []
            if group.get("owner"):
                candidates.append(str(group["owner"]))
            candidates.extend(str(u) for u in (group.get("users") or []))
            roles = userRolesRepository.find({"group": str(group_id), "active": True})
            candidates.extend(str(r.user_uid) for r in roles)
            unique = list(dict.fromkeys(candidates))
            return [uid for uid in unique if can(uid, str(group_id), TEAM_MANAGE_MEMBERS)]
        except Exception:
            logger.exception("whatsapp_usage_notifier manager_uids failed group_id=%s", group_id)
            return []

    def super_admin_uids(self) -> List[str]:
        """Super admins, read from the active `super_admin` rows in UserRoles (nothing to configure)."""
        try:
            return userRolesRepository.distinct_active_uids(SUPER_ADMIN_ROLE)
        except Exception:
            logger.exception("whatsapp_usage_notifier super_admin_uids failed")
            return []

    def is_manager(self, uid: str, group_id: str) -> bool:
        try:
            return bool(can(uid, str(group_id), TEAM_MANAGE_MEMBERS))
        except Exception:
            logger.exception("whatsapp_usage_notifier is_manager failed uid=%s group_id=%s", uid, group_id)
            return False

    @staticmethod
    def _send(uid: str, title: str, body: str, data: dict) -> int:
        try:
            return int(push_service.send_push_to_uid(uid, title=title, body=body, data=data) or 0)
        except Exception:
            logger.exception("whatsapp_usage_notifier push failed uid=%s", uid)
            return 0

    def push_managers(
        self,
        group_id: str,
        store_name: str,
        snapshot: UsageSnapshot,
        kind: Literal["warning", "limit"],
        now: datetime,
    ) -> int:
        when = _renewal(snapshot, now)
        if kind == "warning":
            title = "Tu tienda está por llegar al límite"
            body = f"{store_name} lleva {snapshot.used} de {snapshot.limit} solicitudes de WhatsApp. Se renuevan {when}."
        else:
            title = "Tu tienda llegó al límite"
            body = f"El bot no crea borradores nuevos hasta {when}. Toca para pedir más solicitudes."
        sent = 0
        for uid in self.manager_uids(group_id):
            sent += self._send(uid, title, body, {"navigateToUrl": NAVIGATE_URL})
        return sent

    def push_admins_credit_request(self, group_id: str, store_name: str, requested_by: str) -> int:
        sent = 0
        for uid in self.super_admin_uids():
            sent += self._send(
                uid,
                "Solicitud de más solicitudes de WhatsApp",
                f"{store_name} pidió más solicitudes de WhatsApp.",
                {"navigateToUrl": "/super-admin/whatsapp/credit-requests", "group_id": str(group_id), "requested_by": str(requested_by)},
            )
        return sent

    def push_requester_resolved(
        self, uid: Optional[str], store_name: str, status: Literal["granted", "declined"], amount: Optional[int] = None
    ) -> int:
        """Tell whoever asked for more solicitudes that the Eassymo team reviewed it. Never raises."""
        if not uid:
            return 0
        if status == "granted":
            body = f"Te dimos {amount} solicitudes extra para {store_name}."
        else:
            body = f"Por ahora no pudimos darte más solicitudes para {store_name}."
        try:
            return self._send(str(uid), "Tu solicitud fue revisada", body, {"navigateToUrl": NAVIGATE_URL})
        except Exception:
            logger.exception("whatsapp_usage_notifier push_requester_resolved failed uid=%s", uid)
            return 0
