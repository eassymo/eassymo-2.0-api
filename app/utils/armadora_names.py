import re
import unicodedata
from typing import Dict, Any


def format_armadora_display_name(name: str) -> str:
    """Canonical display form: trimmed with collapsed internal whitespace."""
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.strip())


def normalize_armadora_name(name: str) -> str:
    """
    Dedup key for armadora / make names.
    Strips accents, case-folds, normalizes separators, and collapses whitespace.
    """
    display = format_armadora_display_name(name)
    if not display:
        return ""

    decomposed = unicodedata.normalize("NFD", display)
    without_accents = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    folded = without_accents.casefold()
    separators_normalized = re.sub(r"[-_/.,]+", " ", folded)
    return re.sub(r"\s+", " ", separators_normalized).strip()


def pick_preferred_armadora_display(existing: str, candidate: str) -> str:
    """When variants share the same normalized key, prefer ALL CAPS then shorter."""
    existing_display = format_armadora_display_name(existing)
    candidate_display = format_armadora_display_name(candidate)

    def is_all_caps(value: str) -> bool:
        return bool(value) and value == value.upper() and any(c.isalpha() for c in value)

    if is_all_caps(candidate_display) and not is_all_caps(existing_display):
        return candidate_display
    if is_all_caps(existing_display) and not is_all_caps(candidate_display):
        return existing_display
    if len(candidate_display) < len(existing_display):
        return candidate_display
    return existing_display


def pick_preferred_ensambladora_item(
    existing: Dict[str, Any], candidate: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge duplicate SQL rows: prefer image, then lower ensambladoraId."""
    existing_image = (existing.get("ensambladoraImagen") or "").strip()
    candidate_image = (candidate.get("ensambladoraImagen") or "").strip()

    if candidate_image and not existing_image:
        preferred = dict(candidate)
    elif existing_image and not candidate_image:
        preferred = dict(existing)
    elif candidate.get("ensambladoraId", 0) < existing.get("ensambladoraId", 0):
        preferred = dict(candidate)
    else:
        preferred = dict(existing)

    preferred["ensambladoraNombre"] = pick_preferred_armadora_display(
        existing.get("ensambladoraNombre", ""),
        candidate.get("ensambladoraNombre", ""),
    )
    return preferred
