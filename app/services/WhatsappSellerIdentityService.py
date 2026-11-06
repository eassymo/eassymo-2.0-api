import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.repositories import GroupRepository as groupRepository
from app.repositories import UserRepository as userRepository
from app.repositories import WhatsappPendingAssociationRepository as pending_repo
from app.utils.phone_normalize import normalize_phone_e164, phone_lookup_variants, phones_match

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


class WhatsappSellerIdentityService:
    def __init__(self) -> None:
        self.group_sticky_hours = max(1, int(os.getenv("WHATSAPP_GROUP_STICKY_HOURS", "12")))
        self.selection_prompt_cooldown_seconds = max(
            15, int(os.getenv("WHATSAPP_SELECTION_PROMPT_SECONDS", "60"))
        )

    def _find_user_by_verified_whatsapp(self, from_number: str) -> Optional[dict]:
        normalized = normalize_phone_e164(from_number)
        for variant in phone_lookup_variants(normalized):
            user = userRepository.find_one({"pos_whatsapp": variant})
            if user:
                return user

        users = list(
            userRepository.find(
                {"pos_whatsapp": {"$exists": True, "$nin": [None, ""]}},
                limit=500,
            )
        )
        for user in users:
            stored = user.get("pos_whatsapp") or ""
            if phones_match(normalized, stored):
                return user
        return None

    def _groups_for_user(self, uid: str) -> List[dict]:
        if not uid:
            return []
        return list(groupRepository.find_by_user(uid))

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
        pending = pending_repo.get_by_phone(normalized)

        if pending and self._is_change_store_command(body):
            candidates = pending.get("candidates") or []
            if pending.get("selected_group_id"):
                pending_repo.clear_selected_store(normalized)
            if candidates:
                return SellerIdentityResult(
                    status="pending_selection",
                    candidates=candidates,
                    creator_uid=pending.get("creator_uid"),
                    message=self._selection_prompt(normalized, candidates, force=True),
                )

        if pending and pending.get("selected_group_id"):
            if self._is_sticky_store_stale(pending):
                candidates = pending.get("candidates") or []
                pending_repo.clear_selected_store(normalized)
                if candidates:
                    return SellerIdentityResult(
                        status="pending_selection",
                        candidates=candidates,
                        creator_uid=pending.get("creator_uid"),
                        message=self._selection_prompt(normalized, candidates),
                    )

            group_id = pending.get("selected_group_id")
            group_name = None
            for candidate in pending.get("candidates") or []:
                if candidate.get("group_id") == group_id:
                    group_name = candidate.get("name")
                    break
            pending_repo.touch_last_inbound(normalized)
            return SellerIdentityResult(
                status="resolved",
                group_id=group_id,
                group_name=group_name,
                creator_uid=pending.get("creator_uid"),
            )

        if pending and (pending.get("candidates") or []):
            selected = self._resolve_from_pending_selection(normalized, body, pending)
            if selected:
                return selected
            return SellerIdentityResult(
                status="pending_selection",
                candidates=pending.get("candidates"),
                creator_uid=pending.get("creator_uid"),
                message=self._selection_prompt(normalized, pending.get("candidates") or []),
            )

        user = self._find_user_by_verified_whatsapp(normalized)
        if not user:
            if not pending:
                pending_repo.upsert_pending(normalized, [], inbound_id)
            return SellerIdentityResult(
                status="pending_link",
                message=(
                    "No encontramos tu WhatsApp en Eassymo. En la app ve a "
                    "Mi cuenta → WhatsApp para POS, confirma tu número y reenvía tu mensaje."
                    if pending_repo.claim_identity_prompt(
                        normalized,
                        cooldown_seconds=self.selection_prompt_cooldown_seconds,
                    )
                    else None
                ),
            )

        creator_uid = user.get("uid")
        groups = self._groups_for_user(creator_uid)

        if len(groups) == 1:
            group = groups[0]
            pending_repo.clear(normalized)
            return SellerIdentityResult(
                status="resolved",
                group_id=str(group["_id"]),
                group_name=group.get("name"),
                creator_uid=creator_uid,
            )

        if len(groups) > 1:
            candidates = [self._candidate_payload(g) for g in groups]
            pending_repo.upsert_pending(normalized, candidates, inbound_id)
            return SellerIdentityResult(
                status="pending_selection",
                candidates=candidates,
                creator_uid=creator_uid,
                message=self._selection_prompt(normalized, candidates),
            )

        pending_repo.upsert_pending(normalized, [], inbound_id)
        return SellerIdentityResult(
            status="pending_link",
            message=(
                "Tu WhatsApp está vinculado pero no tienes tienda activa. "
                "Crea o únete a una tienda en Eassymo y reenvía tu mensaje."
            ),
        )
