"""Spanish copy and time formatting for WhatsApp usage limits."""

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.services.WhatsappUsageService import UsageSnapshot

DISPLAY_TZ = ZoneInfo("America/Mexico_City")
_MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

GUARD_NOTICE = "Estás enviando mensajes muy rápido. Espera un momento y vuelve a intentar."


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(DISPLAY_TZ)


def format_when(target: datetime, now: datetime) -> str:
    """'hoy a las 11:40 pm' | 'mañana a las 1:05 am' | 'el 20 nov a las 3:40 pm' (Mexico City)."""
    t, n = _local(target), _local(now)
    hour = t.hour % 12 or 12
    clock = f"{hour}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"
    days = (t.date() - n.date()).days
    if days == 0:
        return f"hoy a las {clock}"
    if days == 1:
        return f"mañana a las {clock}"
    return f"el {t.day} {_MONTHS[t.month - 1]} a las {clock}"


def format_span(window_seconds: int) -> str:
    hours = max(1, round(window_seconds / 3600))
    if hours >= 24 and hours % 24 == 0:
        days = hours // 24
        return f"{days} día" if days == 1 else f"{days} días"
    return f"{hours} hora" if hours == 1 else f"{hours} horas"


def _renewal(snapshot: UsageSnapshot, now: datetime) -> str:
    if snapshot.window_end is None:
        return "pronto"
    return format_when(snapshot.window_end, now)


def warning_message(snapshot: UsageSnapshot, now: datetime) -> str:
    return (
        f"⚠️ Tu tienda lleva {snapshot.used} de {snapshot.limit} solicitudes. "
        f"Se renuevan {_renewal(snapshot, now)}."
    )


def block_message(snapshot: UsageSnapshot, *, is_manager: bool, link: str, now: datetime) -> str:
    base = (
        f"Tu tienda llegó al límite de solicitudes de WhatsApp "
        f"({snapshot.limit} cada {format_span(snapshot.window_seconds)}). "
        f"Se renueva {_renewal(snapshot, now)}."
    )
    if is_manager:
        return f"{base}\n\nPide más en Eassymo POS: {link}"
    return f"{base} Avisa al dueño o encargado si necesitas más ahora."
