def normalize_phone_e164(phone: str) -> str:
    """Normalize a phone string to E.164. Ten-digit numbers get the Mexico +52 prefix."""
    raw = (phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("+") and digits:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+52{digits}"
    if digits:
        return f"+{digits}"
    return raw


def phone_lookup_variants(phone: str) -> list[str]:
    """Include +52 and +521 forms so Twilio mobiles match locally stored numbers."""
    e164 = normalize_phone_e164(phone)
    digits = "".join(ch for ch in e164 if ch.isdigit())
    variants: list[str] = []

    def add(candidate: str | None) -> None:
        if candidate and candidate not in variants:
            variants.append(candidate)

    add(e164)
    stripped = (phone or "").strip()
    add(stripped or None)
    add(f"+{digits}" if digits else None)
    if len(digits) >= 10:
        last10 = digits[-10:]
        add(last10)
        add(f"+52{last10}")
        add(f"+521{last10}")
    if digits.startswith("521") and len(digits) >= 13:
        add(f"+52{digits[3:]}")
    elif digits.startswith("52") and not digits.startswith("521") and len(digits) >= 12:
        add(f"+521{digits[2:]}")
    return variants


def phones_match(left: str, right: str) -> bool:
    return bool(set(phone_lookup_variants(left)) & set(phone_lookup_variants(right)))
