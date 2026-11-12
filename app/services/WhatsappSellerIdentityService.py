import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.repositories import GroupRepository as groupRepository
from app.repositories import WhatsappLinkRepository as link_repo
from app.repositories import WhatsappPendingAssociationRepository as pending_repo
from app.services.access_policy import PERMISSION_WHATSAPP_CREATE_DRAFT, can
from app.utils.phone_normalize import normalize_phone_e164

logger = logging.getLogger(__name__)


@dataclass
class SellerIdentityResult:
    status: str  # resolved | pending_selection | pending_link | ambiguous
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    creator_uid: Optional[str] = None
    candidates: Optional[List[Dict[str, str]]] = None
    message: Optional[str] = None
    just_selected: bool = False


CHANGE_STORE_COMMANDS = frozenset({"CAMBIAR", "MENU", "ATRAS"})

UNLINKED_MESSAGE = (
    "No encontramos tu WhatsApp en Eassymo. En la app ve a Mi cuenta → WhatsApp para POS, "
    "elige tu tienda, confirma tu número y reenvía tu mensaje."
)
NO_ACCESS_MESSAGE = (
    "Tu WhatsApp está vinculado, pero no tienes acceso a WhatsApp POS en ninguna tienda. "
    "Pide acceso al dueño de la tienda."
)
AMBIGUOUS_MESSAGE = "No pudimos identificar tu cuenta. Contacta a soporte."


class WhatsappSellerIdentityService:
    def __init__(self) -> None:
        self.group_sticky_hours = max(1, int(os.getenv("WHATSAPP_GROUP_STICKY_HOURS", "12")))
        self.selection_prompt_cooldown_seconds = max(
            15, int(os.getenv("WHATSAPP_SELECTION_PROMPT_SECONDS", "60"))
        )

    @staticmethod
    def _link_allowed(link: dict) -> bool:
        return link.get("status") == "active" and can(
            link.get("uid"), link.get("group_id"), PERMISSION_WHATSAPP_CREATE_DRAFT
        )

    def is_entitled(self, uid: str, group_id: str) -> bool:
        """True when (uid, group_id) has an active WhatsApp link and the role allows drafts."""
        link = link_repo.find(uid, group_id)
        return bool(link) and self._link_allowed(link)

    def _allowed_candidates(self, links: List[dict]) -> List[Dict[str, str]]:
        """Active, permitted links whose group still exists, in link order."""
        allowed_ids = [str(link.get("group_id")) for link in links if self._link_allowed(link)]
        if not allowed_ids:
            return []
        groups = {
            str(g.get("_id")): g
            for g in groupRepository.find_many_by_string_ids(allowed_ids, {"name": 1})
        }
        return [self._candidate_payload(groups[gid]) for gid in allowed_ids if gid in groups]

    @staticmethod
    def _candidate_payload(group: dict) -> Dict[str, str]:
        gid = group.get("_id")
        return {
            "group_id": str(gid),
            "name": group.get("name") or "Tienda",
        }

    @staticmethod
    def _selection_list_message(candidates: List[Dict[str, str]]) -> str:
        lines = "\n".join(f"{i + 1}. {c['name']}" for i, c in enumerate(candidates))
        return (
            "Tienes varias tiendas en Eassymo. Responde con el número o nombre "
            f"de la tienda para esta solicitud:\n{lines}"
        )

    @staticmethod
    def _normalize_command(body: str) -> str:
        text = (body or "").strip().upper()
        decomposed = unicodedata.normalize("NFD", text)
        return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")

    @classmethod
    def _is_change_store_command(cls, body: str) -> bool:
        return cls._normalize_command(body) in CHANGE_STORE_COMMANDS

    def _is_sticky_store_stale(self, pending: dict) -> bool:
        last_inbound_at = pending.get("last_inbound_at")
        if not last_inbound_at:
            return False
        if last_inbound_at.tzinfo is None:
            last_inbound_at = last_inbound_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_inbound_at).total_seconds()
        return elapsed >= self.group_sticky_hours * 3600

    def _resolve_from_pending_selection(
        self, from_number: str, body: str, pending: dict
    ) -> Optional[SellerIdentityResult]:
        candidates = pending.get("candidates") or []
        if not candidates:
            return None

        text = (body or "").strip().lower()
        if not text:
            return None

        if re.fullmatch(r"\d+", text):
            idx = int(text) - 1
            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                creator_uid = pending.get("creator_uid")
                pending_repo.set_selected_store(
                    from_number, chosen["group_id"], creator_uid
                )
                return SellerIdentityResult(
                    status="resolved",
                    group_id=chosen["group_id"],
                    group_name=chosen.get("name"),
                    creator_uid=creator_uid,
                    just_selected=True,
                )

        for candidate in candidates:
            name = (candidate.get("name") or "").lower()
            if name and name in text:
                creator_uid = pending.get("creator_uid")
                pending_repo.set_selected_store(
                    from_number, candidate["group_id"], creator_uid
                )
                return SellerIdentityResult(
                    status="resolved",
                    group_id=candidate["group_id"],
                    group_name=candidate.get("name"),
                    creator_uid=creator_uid,
                    just_selected=True,
                )
        return None

    def _selection_prompt(
        self,
        from_number: str,
        candidates: List[Dict[str, str]],
        *,
        force: bool = False,
    ) -> Optional[str]:
        if not candidates:
            return None
        claimed = pending_repo.claim_identity_prompt(
            from_number,
            cooldown_seconds=self.selection_prompt_cooldown_seconds,
            force=force,
        )
        if not claimed:
            return None
        return self._selection_list_message(candidates)

    def resolve(
        self, from_number: str, body: str = "", inbound_id: Optional[str] = None
    ) -> SellerIdentityResult:
        normalized = normalize_phone_e164(from_number)
        links = link_repo.find_any_by_phone(normalized)

        uids = {link.get("uid") for link in links}
        if len(uids) > 1:
            logger.error(
                "WhatsApp number %s is linked to %d accounts; refusing to route",
                normalized,
                len(uids),
            )
            return SellerIdentityResult(status="ambiguous", message=AMBIGUOUS_MESSAGE)

        pending = pending_repo.get_by_phone(normalized)

        if not links:
            if not pending:
                pending_repo.upsert_pending(normalized, [], inbound_id)
            return SellerIdentityResult(
                status="pending_link", message=self._throttled(normalized, UNLINKED_MESSAGE)
            )

        creator_uid = links[0].get("uid")
        candidates = self._allowed_candidates(links)

        if not candidates:
            if not pending:
                pending_repo.upsert_pending(normalized, [], inbound_id)
            else:
                if pending.get("selected_group_id"):
                    pending_repo.clear_selected_store(normalized)
                if pending.get("candidates"):
                    pending_repo.set_candidates(normalized, [])
            return SellerIdentityResult(
                status="pending_link", message=self._throttled(normalized, NO_ACCESS_MESSAGE)
            )

        if len(candidates) == 1:
            chosen = candidates[0]
            pending_repo.clear(normalized)
            return SellerIdentityResult(
                status="resolved",
                group_id=chosen["group_id"],
                group_name=chosen["name"],
                creator_uid=creator_uid,
            )

        if not pending:
            pending_repo.upsert_pending(normalized, candidates, inbound_id)
            return self._pending_selection(normalized, candidates, creator_uid)

        if (pending.get("candidates") or []) != candidates:
            pending_repo.set_candidates(normalized, candidates)
        candidate_ids = {c["group_id"] for c in candidates}
        selected_group_id = pending.get("selected_group_id")
        if selected_group_id and selected_group_id not in candidate_ids:
            pending_repo.clear_selected_store(normalized)
            selected_group_id = None
        pending = {
            **pending,
            "candidates": candidates,
            "creator_uid": creator_uid,
            "selected_group_id": selected_group_id,
        }
        return self._resolve_among_candidates(normalized, body, pending)

    def _throttled(self, normalized: str, message: str) -> Optional[str]:
        claimed = pending_repo.claim_identity_prompt(
            normalized, cooldown_seconds=self.selection_prompt_cooldown_seconds
        )
        return message if claimed else None

    def _pending_selection(
        self,
        normalized: str,
        candidates: List[Dict[str, str]],
        creator_uid: Optional[str],
        *,
        force: bool = False,
    ) -> SellerIdentityResult:
        return SellerIdentityResult(
            status="pending_selection",
            candidates=candidates,
            creator_uid=creator_uid,
            message=self._selection_prompt(normalized, candidates, force=force),
        )

    def _resolve_among_candidates(
        self, normalized: str, body: str, pending: dict
    ) -> SellerIdentityResult:
        """Change-store command, sticky selection and picker over fresh candidates.

        `pending` carries the fresh `candidates` and `creator_uid`, and a
        `selected_group_id` already known to be among them (or None).
        """
        candidates = pending["candidates"]
        creator_uid = pending["creator_uid"]
        selected_group_id = pending.get("selected_group_id")

        if self._is_change_store_command(body):
            if selected_group_id:
                pending_repo.clear_selected_store(normalized)
            return self._pending_selection(normalized, candidates, creator_uid, force=True)

        if selected_group_id:
            if self._is_sticky_store_stale(pending):
                pending_repo.clear_selected_store(normalized)
                return self._pending_selection(normalized, candidates, creator_uid)

            group_name = next(
                (c["name"] for c in candidates if c["group_id"] == selected_group_id), None
            )
            pending_repo.touch_last_inbound(normalized)
            return SellerIdentityResult(
                status="resolved",
                group_id=selected_group_id,
                group_name=group_name,
                creator_uid=creator_uid,
            )

        selected = self._resolve_from_pending_selection(normalized, body, pending)
        if selected:
            return selected
        return self._pending_selection(normalized, candidates, creator_uid)
