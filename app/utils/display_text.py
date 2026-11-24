"""Display-text helpers; same rules as the client's dashboard-v3/lib/display-name.ts."""
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

CONNECTORS = {"de", "del", "la", "las", "los", "y", "e", "o", "en", "con"}


def _capitalize(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def display_name(raw: Optional[str]) -> str:
    """Names stored in capitals become Title Case; names already mixed-case are left as typed."""
    value = (raw or "").strip()
    if not value or value != value.upper():
        return value
    out = []
    for index, word in enumerate(value.split()):
        if any(ch.isdigit() for ch in word):
            out.append(word)
        elif index > 0 and word.lower() in CONNECTORS:
            out.append(word.lower())
        else:
            out.append(_capitalize(word))
    return " ".join(out)


def sentence_case(raw: Optional[str]) -> str:
    """Part names arrive in Title Case; acronyms such as PCV are kept."""
    value = (raw or "").strip()
    if not value:
        return value
    out = []
    for index, word in enumerate(value.split()):
        if index == 0:
            out.append(word)
        elif len(word) > 1 and word == word.upper() and any(ch.isalpha() for ch in word):
            out.append(word)
        else:
            out.append(word.lower())
    return " ".join(out)


def vehicle_label(vehicle: Optional[dict]) -> str:
    """Brand + model + year from a vehicleInformation dict; "" when missing."""
    if not vehicle:
        return ""
    brand = vehicle.get("maker") or vehicle.get("brand")
    parts = [brand, vehicle.get("model"), vehicle.get("year")]
    return " ".join(str(p) for p in parts if p)


def local_time_label(value) -> str:
    """'3:17 p. m.' in Mexico City time; accepts a datetime or an ISO string, "" when missing."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    local = value.astimezone(ZoneInfo("America/Mexico_City"))
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'a. m.' if local.hour < 12 else 'p. m.'}"
