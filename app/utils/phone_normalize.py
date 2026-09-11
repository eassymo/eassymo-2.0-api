"""Shared phone normalization for WhatsApp intake and folio lookups."""
from typing import List, Optional, Set


def normalize_phone_e164(phone: str) -> str:
    """Normalize a phone string to E.164 (+52 for 10-digit MX numbers)."""
    raw = (phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("+") and digits:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+52{digits}"
    if digits:
        return f"+{digits}"
    return raw


def phone_lookup_variants(phone: str) -> List[str]:
    """Build comparable phone variants (MX 52 vs 521, last 10 digits)."""
    e164 = normalize_phone_e164(phone)
    digits = "".join(ch for ch in e164 if ch.isdigit())
    variants: List[str] = []
    seen: Set[str] = set()

    def add(candidate: Optional[str]) -> None:
        if not candidate:
            return
        c = candidate.strip()
        if c and c not in seen:
            seen.add(c)
            variants.append(c)

    add(e164)
    add(phone.strip())
    if digits:
        add(f"+{digits}")
    if len(digits) >= 10:
        last10 = digits[-10:]
        add(last10)
        add(f"+52{last10}")
        add(f"+521{last10}")
        if digits.startswith("521") and len(digits) >= 13:
            add(f"+52{digits[3:]}")
        if digits.startswith("52") and not digits.startswith("521") and len(digits) >= 12:
            add(f"+521{digits[2:]}")
    return variants


def phones_match(a: str, b: str) -> bool:
    va = set(phone_lookup_variants(a))
    vb = set(phone_lookup_variants(b))
    return bool(va.intersection(vb))
