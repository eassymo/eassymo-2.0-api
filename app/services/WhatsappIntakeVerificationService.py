import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.repositories import UserRepository as userRepository
from app.repositories import WhatsappNumberVerificationRepository as verify_repo
from app.schemas.WhatasppMessage import WhatsappMessage, WhatsappTemplate
from app.services.WhatsappService import WhatsappService
from app.utils.phone_normalize import normalize_phone_e164, phone_lookup_variants, phones_match

logger = logging.getLogger(__name__)

TTL_MINUTES = 10
CHANGE_WINDOW_MINUTES = 30
RESEND_COOLDOWN_MINUTES = 2
MAX_DISTINCT_PHONES_PER_WINDOW = 2


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) >= 4:
        return f"***{digits[-4:]}"
    return "***"


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None or not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _find_user_by_verified_whatsapp(phone: str) -> Optional[dict]:
    normalized = normalize_phone_e164(phone)
    for variant in phone_lookup_variants(normalized):
        user = userRepository.find_one({"pos_whatsapp": variant})
        if user:
            return user
    users = list(userRepository.find({"pos_whatsapp": {"$exists": True, "$nin": [None, ""]}}))
    for user in users:
        stored = user.get("pos_whatsapp") or ""
        if phones_match(normalized, stored):
            return user
    return None


def _window_start(now: datetime) -> datetime:
    return now - timedelta(minutes=CHANGE_WINDOW_MINUTES)


def _next_change_at(uid: str, now: datetime) -> Optional[datetime]:
    since = _window_start(now)
    starts = verify_repo.list_starts_since(uid, since)
    if len({row.get("phone") for row in starts}) < MAX_DISTINCT_PHONES_PER_WINDOW:
        return None
    created_times = [
        _as_utc(row.get("created_at"))
        for row in starts
        if _as_utc(row.get("created_at")) is not None
    ]
    if not created_times:
        return None
    earliest = min(created_times)
    return earliest + timedelta(minutes=CHANGE_WINDOW_MINUTES)


def _fair_use_flags(uid: str, open_pending: Optional[dict], now: datetime) -> Dict[str, Any]:
    since = _window_start(now)
    distinct = verify_repo.count_distinct_phones(uid, since)
    can_change = distinct < MAX_DISTINCT_PHONES_PER_WINDOW
    next_change_at = None if can_change else _next_change_at(uid, now)

    can_resend = False
    if open_pending:
        last_sent = _as_utc(open_pending.get("last_sent_at") or open_pending.get("created_at"))
        if last_sent and (now - last_sent) >= timedelta(minutes=RESEND_COOLDOWN_MINUTES):
            can_resend = True

    return {
        "can_change": can_change,
        "can_resend": can_resend,
        "next_change_at": _iso(next_change_at),
    }


def _pending_payload(open_pending: dict, fair_use: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "phone": open_pending.get("phone"),
        "masked_phone": _mask_phone(open_pending.get("phone") or ""),
        "expires_at": _iso(open_pending.get("expires_at")),
        **fair_use,
    }


class WhatsappIntakeVerificationService:
    def __init__(self) -> None:
        self.whatsapp_service = WhatsappService()
        self.template_sid = os.getenv("TWILIO_WHATSAPP_VERIFY_TEMPLATE_SID", "").strip()

    def _assert_template_configured(self) -> None:
        if not self.template_sid:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="WhatsApp verification template is not configured",
            )

    def _send_verification(self, uid: str, phone: str) -> Dict[str, Any]:
        token = secrets.token_urlsafe(24)
        token_hash = _hash_token(token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=TTL_MINUTES)

        user = userRepository.find_one({"uid": uid}) or {}
        display_name = (user.get("name") or "").strip() or "usuario"

        message = WhatsappMessage(
            to=phone,
            template=WhatsappTemplate(
                name=self.template_sid,
                variables=[display_name, token],
            ),
        )
        try:
            sent = self.whatsapp_service.send_template_message(message)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to send WhatsApp verify template: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not send WhatsApp verification message",
            )

        verify_repo.insert(
            {
                "uid": uid,
                "phone": phone,
                "token_hash": token_hash,
                "expires_at": expires_at,
                "message_sid": sent.get("message_sid"),
                "consumed_at": None,
                "last_sent_at": now,
            }
        )

        return {
            "message": "Verification WhatsApp sent. Open the message and tap Confirmar.",
            "masked_phone": _mask_phone(phone),
            "expires_in_minutes": TTL_MINUTES,
            "expires_at": _iso(expires_at),
        }

    def start(self, uid: str, raw_phone: str) -> Dict[str, Any]:
        self._assert_template_configured()
        phone = normalize_phone_e164(raw_phone)
        if not phone or len("".join(ch for ch in phone if ch.isdigit())) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid phone number",
            )

        existing_owner = _find_user_by_verified_whatsapp(phone)
        if existing_owner and str(existing_owner.get("uid")) != str(uid):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This WhatsApp number is already linked to another Eassymo account",
            )

        now = datetime.now(timezone.utc)
        open_pending = verify_repo.find_open_by_uid(uid)
        since = _window_start(now)
        distinct = verify_repo.count_distinct_phones(uid, since)

        if open_pending and phones_match(open_pending.get("phone") or "", phone):
            last_sent = _as_utc(open_pending.get("last_sent_at") or open_pending.get("created_at"))
            if last_sent and (now - last_sent) < timedelta(minutes=RESEND_COOLDOWN_MINUTES):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Espera {RESEND_COOLDOWN_MINUTES} minutos antes de reenviar "
                        "al mismo número."
                    ),
                )
            verify_repo.supersede_open(uid)
            return self._send_verification(uid, phone)

        phone_already_in_window = any(
            phones_match(row.get("phone") or "", phone)
            for row in verify_repo.list_starts_since(uid, since)
        )
        if distinct >= MAX_DISTINCT_PHONES_PER_WINDOW and not phone_already_in_window:
            next_at = _next_change_at(uid, now)
            detail = "Ya usaste el cambio de número permitido. Intenta más tarde."
            if next_at:
                detail += f" Podrás intentar de nuevo después de {_iso(next_at)}."
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail,
            )

        if open_pending:
            verify_repo.supersede_open(uid)

        return self._send_verification(uid, phone)

    def _load_pending(self, token: str) -> dict:
        token_hash = _hash_token(token.strip())
        pending = verify_repo.find_by_token_hash(token_hash)
        if not pending:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verification link not found or expired",
            )
        if pending.get("consumed_at"):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Verification link already used",
            )
        expires_at = _as_utc(pending.get("expires_at"))
        if expires_at and expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Verification link expired",
            )
        return pending

    def preview(self, uid: str, token: str) -> Dict[str, Any]:
        pending = self._load_pending(token)
        if str(pending.get("uid")) != str(uid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This verification belongs to another Eassymo account",
            )
        return {
            "masked_phone": _mask_phone(pending.get("phone") or ""),
            "phone": pending.get("phone"),
            "expires_at": _iso(pending.get("expires_at")),
        }

    def confirm(self, uid: str, token: str) -> Dict[str, Any]:
        pending = self._load_pending(token)
        if str(pending.get("uid")) != str(uid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This verification belongs to another Eassymo account",
            )

        phone = pending.get("phone") or ""
        existing_owner = _find_user_by_verified_whatsapp(phone)
        if existing_owner and str(existing_owner.get("uid")) != str(uid):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This WhatsApp number is already linked to another Eassymo account",
            )

        now = datetime.now(timezone.utc)
        userRepository.update_user(
            uid,
            {
                "pos_whatsapp": phone,
                "pos_whatsapp_verified_at": now,
            },
        )
        verify_repo.mark_consumed(_hash_token(token.strip()))
        verify_repo.supersede_open(uid)

        return {
            "message": "WhatsApp linked for POS intake",
            "pos_whatsapp": phone,
            "pos_whatsapp_verified_at": now.isoformat(),
        }

    def get_status(self, uid: str) -> Dict[str, Any]:
        user = userRepository.find_one({"uid": uid})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        now = datetime.now(timezone.utc)
        verified_at = user.get("pos_whatsapp_verified_at")
        verified = bool(user.get("pos_whatsapp"))
        open_pending = verify_repo.find_open_by_uid(uid)
        fair_use = _fair_use_flags(uid, open_pending, now)

        payload: Dict[str, Any] = {
            "pos_whatsapp": user.get("pos_whatsapp"),
            "pos_whatsapp_verified_at": _iso(verified_at),
            "verified": verified,
            "pending": None,
            "can_change": fair_use["can_change"],
            "next_change_at": fair_use["next_change_at"],
        }

        if open_pending:
            payload["pending"] = _pending_payload(open_pending, fair_use)

        return payload
