import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.repositories import UserRepository as userRepository
from app.repositories import WhatsappIntakeVerificationRepository as verify_repo
from app.schemas.WhatasppMessage import WhatsappMessage, WhatsappTemplate
from app.services.WhatsappService import WhatsappService
from app.utils.phone_normalize import normalize_phone_e164, phone_lookup_variants, phones_match

logger = logging.getLogger(__name__)

MAX_DISTINCT_PHONES = 2
CHANGE_WINDOW = timedelta(hours=24)
RESEND_COOLDOWN = timedelta(seconds=60)
PENDING_TTL = timedelta(hours=24)


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


def _canonical_pos_phone(phone: str) -> str:
    normalized = normalize_phone_e164(phone)
    digits = "".join(ch for ch in normalized if ch.isdigit())
    if len(digits) < 10:
        raise HTTPException(
            status_code=400,
            detail="Ingresa un WhatsApp válido de 10 dígitos.",
        )
    if len(digits) == 10:
        return f"+521{digits}"
    if digits.startswith("52") and not digits.startswith("521") and len(digits) == 12:
        return f"+521{digits[2:]}"
    return f"+{digits}"


class WhatsappIntakeVerificationService:
    def __init__(self) -> None:
        self.template_sid = os.getenv(
            "WHATSAPP_TEMPLATE_VERIFY", "wp_eassymo_verification_binder"
        ).strip()
        self.template_language = (
            os.getenv("WHATSAPP_TEMPLATE_VERIFY_LANGUAGE", "en").strip() or "en"
        )

    def start(self, uid: str, phone: str) -> Dict[str, str]:
        user = userRepository.find_one({"uid": uid})
        if not user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")

        canonical = _canonical_pos_phone(phone)
        self._assert_phone_available(canonical, uid)

        now = datetime.now(timezone.utc)
        since = now - CHANGE_WINDOW
        open_pending = verify_repo.find_open_by_uid(uid)
        same_phone = bool(
            open_pending and phones_match(open_pending.get("phone") or "", canonical)
        )
        distinct = verify_repo.count_distinct_phones(uid, since)

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
        verify_repo.supersede_open(uid)
        verify_repo.insert(
            {
                "uid": uid,
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
        logger.info("WhatsApp POS verification sent uid=%s phone=%s", uid, _mask_phone(canonical))
        return {
            "message": "Te enviamos un WhatsApp para confirmar este número.",
            "masked_phone": _mask_phone(canonical),
        }

    def confirm(self, uid: str, token: str) -> Dict[str, Any]:
        pending = self._require_pending(uid, token)
        phone = pending["phone"]
        self._assert_phone_available(phone, uid)
        verified_at = datetime.now(timezone.utc)
        userRepository.update_user(
            uid,
            {
                "pos_whatsapp": phone,
                "pos_whatsapp_verified_at": verified_at,
            },
        )
        verify_repo.mark_consumed(pending.get("token_hash") or _hash_token(token))
        return {
            "pos_whatsapp": phone,
            "pos_whatsapp_verified_at": verified_at.isoformat(),
            "verified": True,
            "pending": None,
            "can_change": True,
        }

    def preview(self, uid: str, token: str) -> Dict[str, str]:
        pending = self._require_pending(uid, token)
        phone = pending.get("phone") or ""
        return {"masked_phone": _mask_phone(phone), "phone": phone}

    def get_status(self, uid: str) -> Dict[str, Any]:
        user = userRepository.find_one({"uid": uid}) or {}
        now = datetime.now(timezone.utc)
        since = now - CHANGE_WINDOW
        pos_whatsapp = user.get("pos_whatsapp") or None
        open_pending = verify_repo.find_open_by_uid(uid)
        if open_pending and self._is_expired(open_pending, now):
            open_pending = None

        distinct = verify_repo.count_distinct_phones(uid, since)
        can_change = distinct < MAX_DISTINCT_PHONES
        next_change_at = None if can_change else self._next_change_at(uid, since)

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
            "pos_whatsapp_verified_at": _iso(user.get("pos_whatsapp_verified_at")),
            "verified": bool(pos_whatsapp),
            "pending": pending,
            "can_change": can_change,
            "next_change_at": _iso(next_change_at),
        }

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
            raise HTTPException(
                status_code=400,
                detail="Esta confirmación venció. Pide un nuevo mensaje.",
            )
        return pending

    def _assert_phone_available(self, phone: str, uid: str) -> None:
        for variant in phone_lookup_variants(phone):
            existing = userRepository.find_one({"pos_whatsapp": variant})
            if not existing:
                continue
            if str(existing.get("uid") or "") == str(uid):
                continue
            stored = existing.get("pos_whatsapp") or ""
            if stored and phones_match(stored, phone):
                raise HTTPException(
                    status_code=409,
                    detail="Este WhatsApp ya está vinculado a otra cuenta.",
                )

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

    def _next_change_at(self, uid: str, since: datetime) -> Optional[datetime]:
        starts = verify_repo.list_starts_since(uid, since)
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
