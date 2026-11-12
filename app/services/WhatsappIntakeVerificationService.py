import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.dependencies import group_auth
from app.repositories import GroupRepository as groupRepository
from app.repositories import UserRepository as userRepository
from app.repositories import WhatsappIntakeVerificationRepository as verify_repo
from app.repositories import WhatsappLinkRepository as link_repo
from app.schemas.WhatasppMessage import WhatsappMessage, WhatsappTemplate
from app.services.access_policy import can, PERMISSION_WHATSAPP_CREATE_DRAFT
from app.services.WhatsappService import WhatsappService
from app.utils.phone_normalize import canonical_pos_phone, phone_lookup_variants, phones_match

logger = logging.getLogger(__name__)

MAX_DISTINCT_PHONES = 2
CHANGE_WINDOW = timedelta(hours=24)
RESEND_COOLDOWN = timedelta(seconds=60)
PENDING_TTL = timedelta(hours=24)

ROLE_DENIED_COPY = "Tu rol en esta tienda no permite usar WhatsApp POS."
LINK_DISABLED_COPY = "El dueño desactivó tu WhatsApp en esta tienda."
EXPIRED_COPY = "Esta confirmación venció. Pide un nuevo mensaje."
PHONE_TAKEN_COPY = "Este WhatsApp ya está vinculado a otra cuenta."


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        ensured = _ensure_utc(value)
        return ensured.isoformat() if ensured else None
    return str(value)


def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    tail = digits[-4:] if digits else ""
    return f"***{tail}"


def _phone_key(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


class WhatsappIntakeVerificationService:
    def __init__(self) -> None:
        self.template_sid = os.getenv(
            "WHATSAPP_TEMPLATE_VERIFY", "wp_eassymo_verification_binder"
        ).strip()
        self.template_language = (
            os.getenv("WHATSAPP_TEMPLATE_VERIFY_LANGUAGE", "es_MX").strip() or "es_MX"
        )

    def start(self, uid: str, group_id: str, phone: str) -> Dict[str, Any]:
        user = userRepository.find_one({"uid": uid})
        if not user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")

        self._assert_can_use(uid, group_id)

        try:
            canonical = canonical_pos_phone(phone)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        self._assert_phone_available(canonical, uid)

        now = datetime.now(timezone.utc)
        if any(
            phones_match(link.get("phone") or "", canonical)
            for link in link_repo.list_by_uid(uid)
        ):
            link_repo.upsert(uid, group_id, canonical, now)
            logger.info(
                "WhatsApp POS link reused uid=%s group=%s phone=%s",
                uid,
                group_id,
                _mask_phone(canonical),
            )
            return {
                "linked": True,
                "pos_whatsapp": canonical,
                "pos_whatsapp_verified_at": now.isoformat(),
                "message": "Vinculamos este número a tu tienda.",
            }

        since = now - CHANGE_WINDOW
        open_pending = verify_repo.find_open(uid, group_id)
        same_phone = bool(
            open_pending and phones_match(open_pending.get("phone") or "", canonical)
        )
        distinct = verify_repo.count_distinct_phones(uid, group_id, since)

        if same_phone and not self._can_resend(open_pending, now):
            raise HTTPException(
                status_code=429,
                detail="Espera un momento antes de reenviar la confirmación.",
            )
        if not same_phone and distinct >= MAX_DISTINCT_PHONES:
            raise HTTPException(
                status_code=429,
                detail="Ya cambiaste de número demasiadas veces. Intenta más tarde.",
            )

        if not self.template_sid:
            raise HTTPException(
                status_code=503,
                detail="La plantilla de WhatsApp no está configurada.",
            )

        token = secrets.token_hex(16)
        token_hash = _hash_token(token)
        verify_repo.supersede_open(uid, group_id)
        verify_repo.insert(
            {
                "uid": uid,
                "group_id": group_id,
                "phone": canonical,
                "token_hash": token_hash,
                "status": "open",
                "expires_at": now + PENDING_TTL,
                "consumed_at": None,
                "created_at": now,
                "last_sent_at": now,
            }
        )

        name = " ".join(str(user.get("name") or "").split())[:60] or "Usuario"
        try:
            WhatsappService().send_template_message(
                WhatsappMessage(
                    to=canonical,
                    template=WhatsappTemplate(
                        name=self.template_sid,
                        language=self.template_language,
                        variables=[name, token],
                    ),
                )
            )
        except Exception:
            verify_repo.mark_failed(token_hash)
            raise
        logger.info(
            "WhatsApp POS verification sent uid=%s group=%s phone=%s",
            uid,
            group_id,
            _mask_phone(canonical),
        )
        return {
            "linked": False,
            "message": "Te enviamos un WhatsApp para confirmar este número.",
            "masked_phone": _mask_phone(canonical),
        }

    def confirm(self, uid: str, token: str) -> Dict[str, Any]:
        pending = self._require_pending(uid, token)
        phone = pending["phone"]
        group_id = str(pending.get("group_id") or "")
        self._assert_can_use(uid, group_id)
        self._assert_phone_available(phone, uid)
        verified_at = datetime.now(timezone.utc)
        link_repo.upsert(uid, group_id, phone, verified_at)
        verify_repo.mark_consumed(pending.get("token_hash") or _hash_token(token))
        return {
            "pos_whatsapp": phone,
            "pos_whatsapp_verified_at": verified_at.isoformat(),
            "verified": True,
            "pending": None,
            "can_change": True,
            "group_id": group_id,
            "link_status": "active",
            "can_use": True,
        }

    def preview(self, uid: str, token: str) -> Dict[str, Any]:
        pending = self._require_pending(uid, token)
        phone = pending.get("phone") or ""
        group_id = str(pending.get("group_id") or "")
        return {
            "masked_phone": _mask_phone(phone),
            "phone": phone,
            "group_id": group_id,
            "group_name": self._group_name(group_id),
        }

    def get_status(self, uid: str, group_id: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        since = now - CHANGE_WINDOW
        link = link_repo.find(uid, group_id) or {}
        pos_whatsapp = link.get("phone") or None
        open_pending = verify_repo.find_open(uid, group_id)
        if open_pending and self._is_expired(open_pending, now):
            open_pending = None

        distinct = verify_repo.count_distinct_phones(uid, group_id, since)
        can_change = distinct < MAX_DISTINCT_PHONES
        next_change_at = None if can_change else self._next_change_at(uid, group_id, since)

        pending = None
        if open_pending:
            pending = {
                "phone": open_pending.get("phone"),
                "masked_phone": _mask_phone(open_pending.get("phone") or ""),
                "expires_at": _iso(open_pending.get("expires_at")),
                "can_resend": self._can_resend(open_pending, now),
                "can_change": can_change,
                "next_change_at": _iso(next_change_at),
            }

        return {
            "pos_whatsapp": pos_whatsapp,
            "pos_whatsapp_verified_at": _iso(link.get("verified_at")),
            "verified": bool(pos_whatsapp),
            "pending": pending,
            "can_change": can_change,
            "next_change_at": _iso(next_change_at),
            "group_id": group_id,
            "group_name": self._group_name(group_id),
            "link_status": link.get("status") if link else None,
            "can_use": bool(can(uid, group_id, PERMISSION_WHATSAPP_CREATE_DRAFT)),
            "suggested_phone": self._suggested_phone(uid, group_id),
        }

    @staticmethod
    def _group_name(group_id: str) -> Optional[str]:
        try:
            group = groupRepository.find_by_id(group_id)
        except Exception:
            return None
        return (group or {}).get("name") or None

    @staticmethod
    def _suggested_phone(uid: str, group_id: str) -> Optional[str]:
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        others = [
            link
            for link in link_repo.list_by_uid(uid)
            if str(link.get("group_id") or "") != str(group_id) and link.get("phone")
        ]
        if not others:
            return None
        newest = max(others, key=lambda l: _ensure_utc(l.get("verified_at")) or epoch)
        return newest["phone"]

    @staticmethod
    def _assert_can_use(uid: str, group_id: str) -> None:
        """Membership, role permission and owner-disable checks for one group."""
        if not group_auth.user_belongs_to_group(uid, group_id):
            raise HTTPException(
                status_code=403, detail="No perteneces a esta tienda."
            )
        if not can(uid, group_id, PERMISSION_WHATSAPP_CREATE_DRAFT):
            raise HTTPException(status_code=403, detail=ROLE_DENIED_COPY)
        link = link_repo.find(uid, group_id)
        if link and link.get("status") == "disabled":
            raise HTTPException(status_code=403, detail=LINK_DISABLED_COPY)

    def _require_pending(self, uid: str, token: str) -> dict:
        raw = (token or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="Falta el token de confirmación.")
        pending = verify_repo.find_by_token_hash(_hash_token(raw))
        if not pending:
            raise HTTPException(
                status_code=404,
                detail="Esta confirmación no existe o ya venció.",
            )
        if str(pending.get("uid") or "") != str(uid):
            raise HTTPException(
                status_code=403,
                detail="Esta confirmación no pertenece a tu cuenta.",
            )
        if pending.get("consumed_at") or pending.get("status") == "consumed":
            raise HTTPException(status_code=400, detail="Esta confirmación ya se usó.")
        if pending.get("superseded_at") or pending.get("status") == "superseded":
            raise HTTPException(
                status_code=400,
                detail="Esta confirmación fue reemplazada. Pide un nuevo mensaje.",
            )
        if self._is_expired(pending, datetime.now(timezone.utc)):
            raise HTTPException(status_code=400, detail=EXPIRED_COPY)
        if not pending.get("group_id"):
            # Issued before per-group links existed: cannot be honoured.
            raise HTTPException(status_code=400, detail=EXPIRED_COPY)
        if not group_auth.user_belongs_to_group(uid, str(pending.get("group_id"))):
            raise HTTPException(status_code=403, detail="No perteneces a esta tienda.")
        return pending

    def _assert_phone_available(self, phone: str, uid: str) -> None:
        for link in link_repo.find_any_by_phone(phone):
            if str(link.get("uid") or "") != str(uid):
                raise HTTPException(status_code=409, detail=PHONE_TAKEN_COPY)
        for variant in phone_lookup_variants(phone):
            existing = userRepository.find_one({"pos_whatsapp": variant})
            if not existing:
                continue
            if str(existing.get("uid") or "") == str(uid):
                continue
            stored = existing.get("pos_whatsapp") or ""
            if stored and phones_match(stored, phone):
                raise HTTPException(status_code=409, detail=PHONE_TAKEN_COPY)

    @staticmethod
    def _is_expired(pending: dict, now: datetime) -> bool:
        expires = _ensure_utc(pending.get("expires_at"))
        return bool(expires and expires <= now)

    @staticmethod
    def _can_resend(pending: Optional[dict], now: datetime) -> bool:
        if not pending:
            return True
        last = _ensure_utc(pending.get("last_sent_at") or pending.get("created_at"))
        if last is None:
            return True
        return now >= last + RESEND_COOLDOWN

    def _next_change_at(self, uid: str, group_id: str, since: datetime) -> Optional[datetime]:
        starts = verify_repo.list_starts_since(uid, group_id, since)
        if not isinstance(starts, list):
            return None
        newest_by_phone: Dict[str, datetime] = {}
        for doc in starts:
            if not isinstance(doc, dict):
                continue
            created = _ensure_utc(doc.get("created_at"))
            key = _phone_key(doc.get("phone") or "")
            if not created or not key:
                continue
            current = newest_by_phone.get(key)
            if current is None or created > current:
                newest_by_phone[key] = created
        if len(newest_by_phone) < MAX_DISTINCT_PHONES:
            return None
        oldest_latest = min(newest_by_phone.values())
        return oldest_latest + CHANGE_WINDOW
