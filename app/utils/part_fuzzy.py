"""Typo- and slang-tolerant matching of what a seller calls a part to the standardized catalog.

Pure functions (no I/O). The catalog is small (hundreds of active parts), so ranking every
description and tag per lookup is cheap and keeps the logic simple and testable.
"""

import re
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence

from app.utils import vehicle_fuzzy as vf

# Words people use for a catalog part ("clutch" is «Embrague», "shocks" are «Amortiguadores»).
PART_SYNONYMS: Dict[str, str] = {
    "clutch": "embrague",
    "cluch": "embrague",
    "croch": "embrague",
    "shock": "amortiguador",
    "shocks": "amortiguador",
    "escobilla": "pluma",
    "escobillas": "pluma",
    "arranque": "marcha",
}

_STOPWORDS = {"de", "del", "la", "el", "los", "las", "para", "con", "y", "en", "a", "un", "una", "unos", "unas", "pa", "mi", "su"}

# Chat filler that sometimes comes back from the model as if it were a part.
NOISE_WORDS = _STOPWORDS | {
    "ok", "okay", "jaja", "jajaja", "jeje", "hola", "buenas", "buenos", "tardes", "dias", "noches", "gracias",
    "si", "no", "porfa", "porfavor", "favor", "urge", "urgente", "precio", "cuanto", "sale", "todo", "tienes",
    "ocupo", "necesito", "quiero", "busco", "pieza", "piezas", "refaccion", "refacciones", "cosa", "cosas",
    "algo", "bro", "oye", "amigo", "jefe", "patron", "ahorita", "luego", "aviso", "mando",
}

SUGGEST_MIN_SCORE = 0.7
AUTO_CORRECT_MIN_SCORE = 0.85
AUTO_CORRECT_MIN_GAP = 0.1
EXTRA_TOKEN_PENALTY = 0.04


# Words a seller adds that say nothing about WHICH part ("clutch completo", "balatas nuevas")
QUALIFIERS = {
    "completo", "completa", "completos", "completas", "nuevo", "nueva", "nuevos", "nuevas", "original",
    "originales", "genuino", "genuina", "usado", "usada", "universal", "estandar", "buen", "buena", "calidad",
}


def _stem(token: str) -> str:
    """Drop a plural ending so 'balatas' and 'balata' compare equal."""
    if len(token) > 5 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def content_tokens(text: str, drop_qualifiers: bool = False) -> List[str]:
    """Folded, plural-stemmed, synonym-resolved tokens without filler words.

    drop_qualifiers is for what the seller wrote ("completo", "nuevas"): never for catalog names.
    """
    out: List[str] = []
    for token in vf.tokenize(text):
        token = PART_SYNONYMS.get(token, token)
        if token in _STOPWORDS or (drop_qualifiers and token in QUALIFIERS):
            continue
        out.append(_stem(token))
    return out


def is_noise_part_name(name: str) -> bool:
    """True when a "part" is empty, has no letters or is only chat filler ("ok", "jajaja")."""
    tokens = vf.tokenize(name)
    if not tokens or not re.search(r"[a-z]", "".join(tokens)):
        return True
    return all(t in NOISE_WORDS for t in tokens) or len("".join(tokens)) < 3


class PartScore(NamedTuple):
    part: dict
    score: float
    extra_tokens: int  # words of the catalog name the seller did not say


def _score_text(query_tokens: Sequence[str], text: str) -> Optional[PartScore]:
    text_tokens = content_tokens(text)
    if not text_tokens:
        return None
    base = vf.score_candidate(query_tokens, text_tokens)
    if base <= 0:
        return None
    extra = max(0, len(set(text_tokens)) - len(set(query_tokens)))
    return PartScore({}, max(0.0, base - EXTRA_TOKEN_PENALTY * extra), extra)


def rank_parts(query: str, parts: Iterable[dict], limit: int = 5) -> List[PartScore]:
    """Catalog parts closest to `query`, best first. Matches on the description and the tags."""
    query_tokens = content_tokens(query, drop_qualifiers=True)
    if not query_tokens:
        return []
    ranked: List[PartScore] = []
    for part in parts:
        best: Optional[PartScore] = None
        for text in [part.get("tipoParteDescripcion", ""), *(part.get("tags") or [])]:
            scored = _score_text(query_tokens, text)
            if scored and (best is None or scored.score > best.score):
                best = scored
        if best and best.score >= SUGGEST_MIN_SCORE - 0.1:
            ranked.append(PartScore(part, best.score, best.extra_tokens))
    ranked.sort(key=lambda s: (-s.score, s.extra_tokens, s.part.get("tipoParteDescripcion", "").lower()))
    return ranked[:limit]


def can_auto_correct(ranked: Sequence[PartScore]) -> bool:
    """A typo'd part may be fixed silently only when it is clearly one part and nothing else is close."""
    if not ranked:
        return False
    best = ranked[0]
    if best.score < AUTO_CORRECT_MIN_SCORE or best.extra_tokens != 0:
        return False
    return len(ranked) == 1 or ranked[1].score <= best.score - AUTO_CORRECT_MIN_GAP


def exact_matches(query: str, parts: Iterable[dict]) -> List[dict]:
    """Parts whose name (or a tag) says exactly what the seller said, ignoring case, accents,
    plurals, filler words and known slang ("clutch" == «Embrague»)."""
    wanted = sorted(content_tokens(query, drop_qualifiers=True))
    if not wanted:
        return []
    found: Dict[object, dict] = {}
    for part in parts:
        for text in [part.get("tipoParteDescripcion", ""), *(part.get("tags") or [])]:
            if sorted(content_tokens(text)) == wanted:
                found.setdefault(part.get("tipoParteId"), part)
                break
    return list(found.values())


def unique_closest(query: str, parts: Iterable[dict], max_extra: int = 1) -> Optional[dict]:
    """The one part whose name contains everything the seller said and the fewest extra words.

    "pluma" -> «Pluma Limpiaparabrisas» (1 extra word, the next closest has 2). "luz" -> None: «Luz Baja»
    and «Luz Alta» tie, so the seller has to choose.
    """
    wanted = set(content_tokens(query, drop_qualifiers=True))
    if not wanted:
        return None
    candidates: List[tuple] = []
    for part in parts:
        best: Optional[int] = None
        for text in [part.get("tipoParteDescripcion", ""), *(part.get("tags") or [])]:
            tokens = set(content_tokens(text))
            if wanted <= tokens:
                extra = len(tokens - wanted)
                best = extra if best is None else min(best, extra)
        if best is not None:
            candidates.append((best, part))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    if candidates[0][0] > max_extra:
        return None
    if len(candidates) > 1 and candidates[1][0] <= candidates[0][0]:
        return None
    return candidates[0][1]
